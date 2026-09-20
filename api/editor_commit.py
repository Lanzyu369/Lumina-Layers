"""Bounded editor-operation receipts and the committed content revision.

编辑操作确认记录与已提交内容版本。

The receipt is deliberately small and short-lived.  It is a confirmation
record for an operation already represented by the existing preview cache,
selection document, and replacement history; it is not a second editor
state or a second history implementation.
"""

from __future__ import annotations

from copy import deepcopy
import time
import uuid
from typing import Any, Literal

from fastapi import HTTPException

from api.session_store import SessionStore
from api.replacement_history import replacement_history_lock
from api.visible_region_cache import get_visible_region_generation

EDITOR_CONTENT_REVISION_KEY = "editor_content_revision"
EDITOR_COMMIT_RECEIPTS_KEY = "editor_commit_receipts"
EDITOR_COMMIT_RECEIPT_LIMIT = 64

EditorCommitStatus = Literal["pending", "committed", "failed", "unknown"]


class EditorCommitReplayError(HTTPException):
    """Reject a duplicate operation id before the editor mutates state.

    在编辑状态发生任何变化前拒绝重复 operation id，避免网络重试重复执行
    替色、撤销或重做。调用方应查询原 operation 的 receipt。
    """

    def __init__(self, operation_id: str, status: str) -> None:
        super().__init__(
            status_code=409,
            detail=(
                f"Editor operation {operation_id!r} already has status "
                f"{status!r}; query its receipt instead of replaying it."
            ),
        )
        self.operation_id = operation_id
        self.receipt_status = status


def get_editor_content_revision(session_data: dict[str, Any]) -> int:
    """Return the monotonic version of all committed output-affecting edits.

    返回所有已提交、会影响输出的编辑操作共用的单调版本。

    Older sessions do not have the new field yet, so the visible-region
    generation is used as a compatibility floor until the first edit advances
    the unified version.
    """
    value = session_data.get(EDITOR_CONTENT_REVISION_KEY)
    try:
        if value is not None:
            return max(0, int(value))
    except (TypeError, ValueError):
        pass
    return max(0, int(get_visible_region_generation(session_data)))


def advance_editor_content_revision(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
) -> int:
    """Advance and persist the unified content version.

    推进并持久化统一内容版本。

    Callers must invoke this while holding the existing per-session editor
    mutation lock, after the cache and session fields for the operation have
    been published and before its receipt is marked committed.
    """
    next_revision = get_editor_content_revision(session_data) + 1
    session_data[EDITOR_CONTENT_REVISION_KEY] = next_revision
    store.put(session_id, EDITOR_CONTENT_REVISION_KEY, next_revision)
    return next_revision


def _receipt_map(session_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = session_data.get(EDITOR_COMMIT_RECEIPTS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(operation_id): deepcopy(value)
        for operation_id, value in raw.items()
        if isinstance(value, dict)
    }


def normalize_editor_operation_id(operation_id: str | None) -> str:
    """Return a bounded client operation id, generating one when absent.

    返回有长度上限的客户端操作 ID；缺失时生成新的 ID。
    """
    value = str(operation_id or "").strip()
    if not value:
        return uuid.uuid4().hex
    if len(value) > 128:
        raise ValueError("editor operation id is too long")
    return value


def begin_editor_commit(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    *,
    operation_id: str | None,
    operation: str,
) -> str:
    """Record that an editor operation has started.

    记录编辑操作开始。该记录用于响应丢失后的确认查询。
    """
    resolved_id = normalize_editor_operation_id(operation_id)
    # Receipt writes are part of the existing per-session editor protocol.
    # 回执写入属于现有的会话级编辑协议，不能与历史/缓存发布脱节。
    with replacement_history_lock(session_id):
        receipts = _receipt_map(session_data)
        existing = receipts.get(resolved_id)
        if existing is None:
            now = time.time()
            receipts[resolved_id] = {
                "operation_id": resolved_id,
                "operation": str(operation),
                "status": "pending",
                "editor_content_revision": get_editor_content_revision(session_data),
                "started_at": now,
                "updated_at": now,
            }
            _persist_receipts(session_id, store, session_data, receipts)
        else:
            raise EditorCommitReplayError(
                resolved_id,
                str(existing.get("status") or "unknown"),
            )
        return resolved_id


def publish_editor_commit(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    *,
    operation_id: str,
    editor_content_revision: int | None = None,
    selection_revision: int | None = None,
) -> dict[str, Any]:
    """Mark an operation committed at the convergence point.

    在所有相关缓存、会话字段和历史都写入后，把操作标记为已提交。
    """
    with replacement_history_lock(session_id):
        receipts = _receipt_map(session_data)
        now = time.time()
        receipt = receipts.get(operation_id, {
            "operation_id": operation_id,
            "operation": "unknown",
            "started_at": now,
        })
        revision = (
            get_editor_content_revision(session_data)
            if editor_content_revision is None
            else int(editor_content_revision)
        )
        receipt.update(
            {
                "status": "committed",
                "editor_content_revision": revision,
                "visible_content_revision": get_visible_region_generation(session_data),
                "selection_revision": selection_revision,
                "updated_at": now,
            }
        )
        receipts[operation_id] = receipt
        _persist_receipts(session_id, store, session_data, receipts)
        return deepcopy(receipt)


def fail_editor_commit(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    *,
    operation_id: str,
    error_type: str,
) -> dict[str, Any]:
    """Mark a known pre-commit failure without claiming a rollback.

    标记已知的提交前失败；只有调用方明确知道尚未发布时才使用。
    """
    with replacement_history_lock(session_id):
        receipts = _receipt_map(session_data)
        now = time.time()
        receipt = receipts.get(operation_id, {
            "operation_id": operation_id,
            "operation": "unknown",
            "started_at": now,
        })
        receipt.update(
            {
                "status": "failed",
                "editor_content_revision": get_editor_content_revision(session_data),
                "error_type": str(error_type),
                "updated_at": now,
            }
        )
        receipts[operation_id] = receipt
        _persist_receipts(session_id, store, session_data, receipts)
        return deepcopy(receipt)


def get_editor_commit_receipt(
    session_data: dict[str, Any],
    operation_id: str,
) -> dict[str, Any] | None:
    """Read one operation receipt without inferring from a version delta.

    读取单个操作确认记录，不根据内容版本差值猜测操作结果。
    """
    receipt = _receipt_map(session_data).get(str(operation_id))
    return deepcopy(receipt) if receipt is not None else None


def _persist_receipts(
    session_id: str,
    store: SessionStore,
    session_data: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
) -> None:
    ordered = sorted(
        receipts.items(),
        key=lambda item: float(item[1].get("updated_at", 0.0)),
    )
    bounded = dict(ordered[-EDITOR_COMMIT_RECEIPT_LIMIT:])
    session_data[EDITOR_COMMIT_RECEIPTS_KEY] = bounded
    store.put(session_id, EDITOR_COMMIT_RECEIPTS_KEY, bounded)
