"""Unit tests for ``api.feedback_assembler`` — sync + startup cleanup.

测试覆盖：
- :func:`collect_sync_attachments` 在 mock FileRegistry 下的原图 / 产物收集
- session 缺失时标记 ``unavailable_after_cleanup``
- :func:`run_startup_cleanup` 对中断工单与过期附件的处理
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.feedback_assembler import (
    SyncCollectionResult,
    collect_sync_attachments,
    run_startup_cleanup,
)
from api.feedback_time import BEIJING_TZ, now_beijing


class _MockFileRegistry:
    """Tiny stand-in for :class:`api.file_registry.FileRegistry`.

    迷你版 FileRegistry，实现本测试文件需要的查询接口。
    """

    def __init__(self, entries_by_session: dict[str, dict[str, dict[str, Any]]]) -> None:
        self._entries_by_session = entries_by_session
        self._entries_by_id = {
            file_id: entry
            for entries in entries_by_session.values()
            for file_id, entry in entries.items()
        }

    def get_session_entries(self, session_id: str) -> dict[str, dict[str, Any]]:
        return dict(self._entries_by_session.get(session_id, {}))

    def get_entry(self, file_id: str) -> dict[str, Any] | None:
        entry = self._entries_by_id.get(file_id)
        return dict(entry) if entry is not None else None

    def resolve(self, file_id: str) -> tuple[str, str] | None:
        entry = self._entries_by_id.get(file_id)
        if entry is None:
            return None
        path = str(entry.get("path") or "")
        filename = str(entry.get("filename") or Path(path).name)
        if not path or not Path(path).is_file():
            return None
        return path, filename


class _MockSessionStore:
    def __init__(self, sessions: dict[str, dict[str, Any]]) -> None:
        self._sessions = sessions

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)


def _make_entry(
    path: str,
    filename: str,
    *,
    created_at: float,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "path": path,
        "filename": filename,
        "created_at": created_at,
        **extra,
    }


def test_collect_sync_attachments_copies_original_and_final(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Original image + final 3MF manifests are built with correct fingerprints.

    原图与最终 3MF 的 manifest 包含正确的 SHA256 与字节大小。
    """
    target_logger = logging.getLogger("lumina.api.feedback_assembler")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)

    src_dir = tmp_path / "source"
    src_dir.mkdir()
    image_path = src_dir / "hello.png"
    image_path.write_bytes(b"PNGDATA")
    artifact_path = src_dir / "model.3mf"
    artifact_path.write_bytes(b"3MFDATA")

    registry = _MockFileRegistry(
        {
            "sess-orig": {
                "f1": _make_entry(str(image_path), "hello.png", created_at=1.0),
                "f2": _make_entry(str(image_path), "layer_preview.png", created_at=2.0),
            },
            "sess-final": {
                "f1": _make_entry(str(artifact_path), "model.3mf", created_at=5.0),
            },
        }
    )

    ticket_dir = tmp_path / "LUM-20260511-001"
    ticket_dir.mkdir()
    payload: dict[str, Any] = {
        "ticket_id": "LUM-20260511-001",
        "context": {
            "active_original_image_ref": {"session_id": "sess-orig"},
            "active_final_artifact_ref": {
                "session_id": "sess-final",
                "artifact_type": "3mf",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(
        ticket_dir=ticket_dir,
        payload=payload,
        file_registry=registry,
        now=now_beijing(),
    )

    assert isinstance(result, SyncCollectionResult)
    assert result.original_image["status"] == "attached"
    assert result.original_image["filename"] == "original.png"
    assert result.original_image["size_bytes"] == len(b"PNGDATA")
    assert (ticket_dir / "original.png").exists()

    assert result.final_artifact["status"] == "attached"
    assert result.final_artifact["filename"] == "final.3mf"
    assert result.final_artifact["artifact_type"] == "3mf"
    assert result.final_artifact["history_count"] == 1
    assert (ticket_dir / "final.3mf").exists()

    assert result.lut["status"] == "not_applicable"
    attachment_logs = [
        r for r in caplog.records
        if getattr(r, "event", None) == "feedback_attachment_collected"
    ]
    assert any(getattr(r, "attachment_kind", None) == "original_image" for r in attachment_logs)
    assert any(getattr(r, "attachment_kind", None) == "final_artifact" for r in attachment_logs)


def test_collect_sync_attachments_marks_unavailable_when_session_missing(
    tmp_path: Path,
) -> None:
    """A session with no matching entries reports ``unavailable_after_cleanup``.

    session 存在但找不到匹配条目时标记为 ``unavailable_after_cleanup``。
    """
    registry = _MockFileRegistry(
        {"sess-orig": {"f1": _make_entry("/nonexistent/path.png", "layer_preview.png", created_at=1.0)}}
    )
    ticket_dir = tmp_path / "LUM-20260511-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-001",
        "context": {
            "active_original_image_ref": {"session_id": "sess-orig"},
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())
    # The only entry is a preview-suffixed image; it is filtered out by the
    # heuristic, so from the perspective of the collector the source image is
    # unavailable.
    assert result.original_image["status"] == "unavailable_after_cleanup"
    assert result.original_image["filename"] is None
    assert result.original_image["source_session_id"] == "sess-orig"


def test_collect_original_image_falls_back_to_session_image_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    source_image = temp_root / "uploaded.png"
    source_image.write_bytes(b"ORIGINAL_PNG")
    monkeypatch.setattr("api.feedback_assembler.TEMP_DIR", str(temp_root))

    registry = _MockFileRegistry({})
    session_store = _MockSessionStore({"sess-orig": {"image_path": str(source_image)}})
    ticket_dir = tmp_path / "LUM-20260511-020"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-020",
        "context": {
            "active_original_image_ref": {"session_id": "sess-orig"},
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(
        ticket_dir,
        payload,
        registry,
        now_beijing(),
        session_store=session_store,
    )

    assert result.original_image["status"] == "attached"
    assert result.original_image["filename"] == "original.png"
    assert result.original_image["size_bytes"] == len(b"ORIGINAL_PNG")
    assert (ticket_dir / "original.png").read_bytes() == b"ORIGINAL_PNG"


def test_collect_original_image_session_image_path_outside_temp_not_copied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(b"OUTSIDE")
    monkeypatch.setattr("api.feedback_assembler.TEMP_DIR", str(temp_root))

    registry = _MockFileRegistry({})
    session_store = _MockSessionStore({"sess-orig": {"image_path": str(outside_image)}})
    ticket_dir = tmp_path / "LUM-20260511-021"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-021",
        "context": {
            "active_original_image_ref": {"session_id": "sess-orig"},
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(
        ticket_dir,
        payload,
        registry,
        now_beijing(),
        session_store=session_store,
    )

    assert result.original_image["status"] == "unavailable_after_cleanup"
    assert not (ticket_dir / "original.png").exists()


def test_collect_original_image_registry_hit_takes_priority_over_session_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    registry_image = tmp_path / "registry.png"
    registry_image.write_bytes(b"REGISTRY")
    session_image = temp_root / "session.png"
    session_image.write_bytes(b"SESSION")
    monkeypatch.setattr("api.feedback_assembler.TEMP_DIR", str(temp_root))

    registry = _MockFileRegistry(
        {"sess-orig": {"f1": _make_entry(str(registry_image), "registry.png", created_at=1.0)}}
    )
    session_store = _MockSessionStore({"sess-orig": {"image_path": str(session_image)}})
    ticket_dir = tmp_path / "LUM-20260511-022"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-022",
        "context": {
            "active_original_image_ref": {"session_id": "sess-orig"},
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(
        ticket_dir,
        payload,
        registry,
        now_beijing(),
        session_store=session_store,
    )

    assert result.original_image["status"] == "attached"
    assert (ticket_dir / "original.png").read_bytes() == b"REGISTRY"


def test_collect_sync_attachments_lut_is_noop_for_material_mode(
    tmp_path: Path,
) -> None:
    registry = _MockFileRegistry({})
    ticket_dir = tmp_path / "LUM-20260511-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-001",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "source_version": "material",
            "lut_name": "AnythingCustom",
        },
    }
    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())
    assert result.lut["status"] == "not_applicable"


def _write_ticket(
    feedback_root: Path,
    ticket_id: str,
    *,
    received_at: datetime,
    assembly_status: str,
    with_bulky: bool = True,
) -> Path:
    month_dir = feedback_root / received_at.strftime("%Y-%m")
    ticket_dir = month_dir / ticket_id
    ticket_dir.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "ticket_id": ticket_id,
        "received_at_cst": received_at.isoformat(),
        "assembly_status": assembly_status,
        "attachments": {},
    }
    (ticket_dir / "ticket.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if with_bulky:
        (ticket_dir / "original.png").write_bytes(b"PNGDATA")
        (ticket_dir / "final.3mf").write_bytes(b"3MFDATA")
        (ticket_dir / "materials.zip").write_bytes(b"ZIPDATA")
        (ticket_dir / "screenshot.png").write_bytes(b"PNG")
        (ticket_dir / "lut.npy").write_bytes(b"LUT")
    (ticket_dir / "index.md").write_text("# index", encoding="utf-8")
    (ticket_dir / "summary.txt").write_text("summary", encoding="utf-8")
    return ticket_dir


def test_run_startup_cleanup_marks_interrupted_tickets(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    target_logger = logging.getLogger("lumina.api.feedback_assembler")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    feedback_root = tmp_path / "feedback"
    old = now_beijing() - timedelta(minutes=30)
    ticket_dir = _write_ticket(
        feedback_root,
        "LUM-20260511-001",
        received_at=old,
        assembly_status="in_progress",
        with_bulky=False,
    )

    counters = run_startup_cleanup(feedback_root)

    assert counters["interrupted"] == 1
    payload = json.loads((ticket_dir / "ticket.json").read_text(encoding="utf-8"))
    assert payload["assembly_status"] == "interrupted"
    warnings = [
        r for r in caplog.records
        if getattr(r, "event", None) == "feedback_ticket_assembly_interrupted"
    ]
    assert warnings
    assert warnings[0].ticket_id == "LUM-20260511-001"


def test_run_startup_cleanup_prunes_bulky_after_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feedback_root = tmp_path / "feedback"
    # Use a tiny TTL so the ticket is immediately expired.
    monkeypatch.setenv("LUMINA_FEEDBACK_TICKET_TTL_DAYS", "1")
    expired = now_beijing() - timedelta(days=5)
    ticket_dir = _write_ticket(
        feedback_root,
        "LUM-20260501-001",
        received_at=expired,
        assembly_status="done",
        with_bulky=True,
    )

    counters = run_startup_cleanup(feedback_root)

    assert counters["pruned"] >= 1
    # Bulky files should be removed.
    assert not (ticket_dir / "original.png").exists()
    assert not (ticket_dir / "final.3mf").exists()
    assert not (ticket_dir / "materials.zip").exists()
    assert not (ticket_dir / "screenshot.png").exists()
    assert not (ticket_dir / "lut.npy").exists()
    # Small metadata preserved.
    assert (ticket_dir / "ticket.json").exists()
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


def test_run_startup_cleanup_noop_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
    feedback_root = tmp_path / "feedback"
    old = now_beijing() - timedelta(minutes=30)
    _write_ticket(
        feedback_root,
        "LUM-20260511-001",
        received_at=old,
        assembly_status="in_progress",
        with_bulky=False,
    )
    counters = run_startup_cleanup(feedback_root)
    assert counters == {"interrupted": 0, "pruned": 0}


def test_run_startup_cleanup_missing_root_returns_zero(tmp_path: Path) -> None:
    counters = run_startup_cleanup(tmp_path / "does-not-exist")
    assert counters == {"interrupted": 0, "pruned": 0}


# ---------------------------------------------------------------------------
# disk_path fallback tests for _collect_final_artifact
# ---------------------------------------------------------------------------


def test_collect_final_artifact_rejects_unregistered_disk_path_when_registry_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client-provided disk_path must not authorize final-artifact attachment.

    客户端传来的 disk_path 不能作为最终产物附件的授权来源。
    """
    from api.feedback_assembler import REPO_ROOT

    # Create a fake 3MF inside REPO_ROOT/output so the path check passes.
    output_dir = REPO_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    fake_3mf = output_dir / "models" / "test_fallback.3mf"
    fake_3mf.parent.mkdir(parents=True, exist_ok=True)
    fake_3mf.write_bytes(b"PK\x03\x04" + b"\x00" * 50)

    try:
        registry = _MockFileRegistry({})
        ticket_dir = tmp_path / "LUM-20260511-010"
        ticket_dir.mkdir()
        payload = {
            "ticket_id": "LUM-20260511-010",
            "context": {
                "active_original_image_ref": None,
                "active_final_artifact_ref": {
                    "session_id": "sess-random-uuid",
                    "artifact_type": "3mf",
                    "disk_path": str(fake_3mf),
                },
                "source_version": "legacy",
                "lut_name": None,
            },
        }

        result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

        assert result.final_artifact["status"] == "expired_ttl"
        assert result.final_artifact["filename"] is None
        assert result.final_artifact["artifact_type"] == "3mf"
        assert not (ticket_dir / "final.3mf").exists()
    finally:
        fake_3mf.unlink(missing_ok=True)
        # Clean up the test file but leave the directory structure.


def test_collect_final_artifact_disk_path_nonexistent_stays_expired(
    tmp_path: Path,
) -> None:
    """disk_path points to a file that does not exist → expired_ttl.

    disk_path 指向不存在的文件时，保持 expired_ttl。
    """
    registry = _MockFileRegistry({})
    ticket_dir = tmp_path / "LUM-20260511-011"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-011",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-random-uuid",
                "artifact_type": "3mf",
                "disk_path": "/nonexistent/path/model.3mf",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_final_artifact_uses_download_url_for_ttl_zip(
    tmp_path: Path,
) -> None:
    """A large-format TTL ZIP can be copied by its exact /api/files URL.

    大画幅 ZIP 可能不挂在当前业务 session 下，应能按下载 URL 精确复制。
    """
    zip_path = tmp_path / "large_format_tiles.zip"
    zip_path.write_bytes(b"PK\x03\x04LARGE_FORMAT")
    registry = _MockFileRegistry(
        {
            "foreign-ttl-owner": {
                "zip-file-id": _make_entry(
                    str(zip_path),
                    "large_format_tiles.zip",
                    created_at=9.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260524-001",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/api/files/zip-file-id?download=1",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "attached"
    assert result.final_artifact["filename"] == "final.zip"
    assert result.final_artifact["artifact_type"] == "zip"
    assert result.final_artifact["history_count"] == 1
    assert (ticket_dir / "final.zip").read_bytes() == b"PK\x03\x04LARGE_FORMAT"


def test_collect_final_artifact_download_url_must_be_api_files_path(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "large_format_tiles.zip"
    zip_path.write_bytes(b"PK\x03\x04LARGE_FORMAT")
    registry = _MockFileRegistry(
        {
            "foreign-ttl-owner": {
                "zip-file-id": _make_entry(
                    str(zip_path),
                    "large_format_tiles.zip",
                    created_at=9.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-002"
    ticket_dir.mkdir()
    payload = {
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/downloads/zip-file-id",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.zip").exists()


def test_collect_final_artifact_download_url_rejects_absolute_url(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "large_format_tiles.zip"
    zip_path.write_bytes(b"PK\x03\x04LARGE_FORMAT")
    registry = _MockFileRegistry(
        {
            "foreign-ttl-owner": {
                "zip-file-id": _make_entry(
                    str(zip_path),
                    "large_format_tiles.zip",
                    created_at=9.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-006"
    ticket_dir.mkdir()
    payload = {
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "https://example.test/api/files/zip-file-id",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.zip").exists()


def test_collect_final_artifact_download_url_requires_artifact_suffix(
    tmp_path: Path,
) -> None:
    png_path = tmp_path / "preview.png"
    png_path.write_bytes(b"PNG")
    registry = _MockFileRegistry(
        {
            "foreign-ttl-owner": {
                "preview-file-id": _make_entry(
                    str(png_path),
                    "preview.png",
                    created_at=9.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-003"
    ticket_dir.mkdir()
    payload = {
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/api/files/preview-file-id",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.png").exists()


def test_collect_final_artifact_download_url_rejects_private_registry_entry(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "private_tiles.zip"
    zip_path.write_bytes(b"PK\x03\x04PRIVATE")
    registry = _MockFileRegistry(
        {
            "foreign-private-owner": {
                "private-zip-id": _make_entry(
                    str(zip_path),
                    "private_tiles.zip",
                    created_at=9.0,
                    is_public=False,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-004"
    ticket_dir.mkdir()
    payload = {
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/api/files/private-zip-id",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.zip").exists()


def test_collect_final_artifact_download_url_rejects_foreign_session_bound_entry(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "session_tiles.zip"
    zip_path.write_bytes(b"PK\x03\x04SESSION")
    registry = _MockFileRegistry(
        {
            "other-session": {
                "session-zip-id": _make_entry(
                    str(zip_path),
                    "session_tiles.zip",
                    created_at=9.0,
                    lifecycle="session_bound",
                    session_id="other-session",
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-005"
    ticket_dir.mkdir()
    payload = {
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/api/files/session-zip-id",
                "artifact_type": "zip",
                "disk_path": None,
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.zip").exists()


def test_collect_final_artifact_disk_path_wrong_extension_not_copied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """disk_path with disallowed extension (.png) is not copied.

    disk_path 指向不允许扩展名的文件时不复制。
    """
    from api.feedback_assembler import REPO_ROOT

    output_dir = REPO_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    bad_file = output_dir / "models" / "not_a_model.png"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_bytes(b"PNG data")

    try:
        registry = _MockFileRegistry({})
        ticket_dir = tmp_path / "LUM-20260511-012"
        ticket_dir.mkdir()
        payload = {
            "ticket_id": "LUM-20260511-012",
            "context": {
                "active_original_image_ref": None,
                "active_final_artifact_ref": {
                    "session_id": "sess-random-uuid",
                    "artifact_type": "3mf",
                    "disk_path": str(bad_file),
                },
                "source_version": "legacy",
                "lut_name": None,
            },
        }

        result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

        assert result.final_artifact["status"] == "expired_ttl"
        assert not (ticket_dir / "final.3mf").exists()
        assert not (ticket_dir / "final.png").exists()
    finally:
        bad_file.unlink(missing_ok=True)


def test_collect_final_artifact_disk_path_outside_output_not_copied(
    tmp_path: Path,
) -> None:
    """disk_path outside REPO_ROOT/output is rejected.

    disk_path 指向 REPO_ROOT/output 外部路径时不复制。
    """
    # Create a file outside the allowed output directory.
    outside_file = tmp_path / "evil.3mf"
    outside_file.write_bytes(b"PK\x03\x04" + b"\x00" * 50)

    registry = _MockFileRegistry({})
    ticket_dir = tmp_path / "LUM-20260511-013"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260511-013",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-random-uuid",
                "artifact_type": "3mf",
                "disk_path": str(outside_file),
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_final_artifact_registry_hit_takes_priority_over_disk_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FileRegistry has a match, disk_path is not used.

    FileRegistry 命中时，disk_path 不会被使用。
    """
    from api.feedback_assembler import REPO_ROOT

    # Create a file in the registry.
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    registry_3mf = src_dir / "registry_model.3mf"
    registry_3mf.write_bytes(b"REGISTRY_3MF")

    # Also create a disk_path file (different content).
    output_dir = REPO_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    disk_3mf = output_dir / "models" / "disk_model.3mf"
    disk_3mf.parent.mkdir(parents=True, exist_ok=True)
    disk_3mf.write_bytes(b"DISK_3MF_DIFFERENT")

    try:
        registry = _MockFileRegistry(
            {
                "sess-final": {
                    "f1": _make_entry(str(registry_3mf), "registry_model.3mf", created_at=5.0),
                },
            }
        )
        ticket_dir = tmp_path / "LUM-20260511-014"
        ticket_dir.mkdir()
        payload = {
            "ticket_id": "LUM-20260511-014",
            "context": {
                "active_original_image_ref": None,
                "active_final_artifact_ref": {
                    "session_id": "sess-final",
                    "artifact_type": "3mf",
                    "disk_path": str(disk_3mf),
                },
                "source_version": "legacy",
                "lut_name": None,
            },
        }

        result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

        assert result.final_artifact["status"] == "attached"
        # Should have the registry file content, not the disk_path content.
        assert (ticket_dir / "final.3mf").read_bytes() == b"REGISTRY_3MF"
    finally:
        disk_3mf.unlink(missing_ok=True)
