"""Unit tests for ``api.feedback_assembler`` — sync + startup cleanup.

测试覆盖：
- :func:`collect_sync_attachments` 在 mock FileRegistry 下的原图 / 产物收集
- session 缺失时标记 ``unavailable_after_cleanup``
- :func:`run_startup_cleanup` 对中断工单与过期附件的处理
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import struct
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.feedback_assembler import (
    SyncCollectionResult,
    collect_direct_original_upload,
    collect_sync_attachments,
    finalize_ticket_async,
    run_startup_cleanup,
)
from api.feedback_time import BEIJING_TZ, now_beijing
from utils.lut_manager import LUTManager


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


class _ChunkedUpload:
    def __init__(self, *chunks: bytes | Exception) -> None:
        self.filename = "source.png"
        self.size = None
        self._chunks = list(chunks)

    async def seek(self, _offset: int) -> None:
        return None

    async def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        value = self._chunks.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_direct_original_short_read_failure_removes_partial_file(
    tmp_path: Path,
) -> None:
    ticket_dir = tmp_path / "LUM-202608-deadbeef"
    ticket_dir.mkdir()
    upload = _ChunkedUpload(b"PARTIAL", OSError("read failed"))

    result = asyncio.run(
        collect_direct_original_upload(
            ticket_dir,
            upload,  # type: ignore[arg-type]
            session_id=None,
        )
    )

    assert result["status"] == "failed"
    assert result["direct_upload_status"] == "failed"
    assert result["error_type"] == "OSError"
    assert not (ticket_dir / "original.png").exists()


def test_direct_original_stream_is_not_cut_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir = tmp_path / "LUM-202608-c0ffee00"
    ticket_dir.mkdir()
    upload = _ChunkedUpload(b"123", b"45")
    monkeypatch.setattr(
        "api.feedback_assembler.MAX_DIRECT_ORIGINAL_IMAGE_BYTES",
        4,
        raising=False,
    )

    result = asyncio.run(
        collect_direct_original_upload(
            ticket_dir,
            upload,  # type: ignore[arg-type]
            session_id=None,
        )
    )

    assert result["status"] == "attached"
    assert result["direct_upload_status"] == "attached"
    assert (ticket_dir / "original.png").read_bytes() == b"12345"


def test_direct_original_short_write_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir = tmp_path / "LUM-202608-5a07a11e"
    ticket_dir.mkdir()
    destination = ticket_dir / "original.png"
    upload = _ChunkedUpload(b"ORIGINAL_BYTES")
    real_path_open = Path.open

    class _ShortWriter:
        def __enter__(self):
            self._output = real_path_open(destination, "xb")
            return self

        def write(self, chunk: bytes) -> int:
            self._output.write(chunk[:1])
            return 1

        def __exit__(self, exc_type, exc, traceback) -> None:
            self._output.close()

    def _short_open(path: Path, mode: str):
        assert path == destination
        assert mode == "xb"
        return _ShortWriter()

    monkeypatch.setattr(Path, "open", _short_open)

    result = asyncio.run(
        collect_direct_original_upload(
            ticket_dir,
            upload,  # type: ignore[arg-type]
            session_id=None,
        )
    )

    assert result["status"] == "failed"
    assert result["direct_upload_status"] == "failed"
    assert result["error_type"] == "OSError"
    assert not destination.exists()


def test_direct_original_collision_does_not_delete_existing_file(
    tmp_path: Path,
) -> None:
    ticket_dir = tmp_path / "LUM-202608-1ee7c0de"
    ticket_dir.mkdir()
    destination = ticket_dir / "original.png"
    destination.write_bytes(b"EXISTING")

    result = asyncio.run(
        collect_direct_original_upload(
            ticket_dir,
            _ChunkedUpload(b"NEW"),  # type: ignore[arg-type]
            session_id=None,
        )
    )

    assert result["status"] == "failed"
    assert result["error_type"] == "FileExistsError"
    assert destination.read_bytes() == b"EXISTING"


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


def _disable_feedback_upload(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")


def _project_bytes(
    marker: bytes,
    settings: dict[str, Any] | None = None,
    *,
    damaged_metadata: bool = False,
) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as package:
        if damaged_metadata:
            package.writestr(
                "Metadata/inspection.json", "{}", compress_type=zipfile.ZIP_DEFLATED,
            )
        package.writestr("3D/3dmodel.model", marker)
        package.writestr(
            "Metadata/project_settings.config",
            json.dumps(settings or {"layer_height": "0.2"}),
        )
    content = bytearray(payload.getvalue())
    if damaged_metadata:
        name_size, extra_size = struct.unpack_from("<HH", content, 26)
        # Set the reserved Deflate block type without corrupting later members.
        content[30 + name_size + extra_size] |= 0x06
    return bytes(content)


def _batch_bytes(marker: bytes) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as package:
        package.writestr("tile/model.3mf", _project_bytes(marker))
    return payload.getvalue()


def test_collect_sync_attachments_copies_original_and_final(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Original image and final artifact are copied with descriptive metadata.

    原图与最终 3MF 保持源文件字节，并记录文件名与字节大小。
    """
    target_logger = logging.getLogger("lumina.api.feedback_assembler")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)

    src_dir = tmp_path / "source"
    src_dir.mkdir()
    image_path = src_dir / "hello.png"
    image_path.write_bytes(b"PNGDATA")
    artifact_path = src_dir / "model.3mf"
    artifact_path.write_bytes(_project_bytes(b"3MFDATA"))

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
    assert (ticket_dir / "original.png").read_bytes() == image_path.read_bytes()
    assert "sha256" not in result.original_image

    assert result.final_artifact["status"] == "attached"
    assert result.final_artifact["filename"] == "final.3mf"
    assert result.final_artifact["artifact_type"] == "3mf"
    assert result.final_artifact["history_count"] == 1
    assert (ticket_dir / "final.3mf").read_bytes() == artifact_path.read_bytes()
    assert "sha256" not in result.final_artifact

    assert result.lut["status"] == "not_applicable"
    attachment_logs = [
        r for r in caplog.records
        if getattr(r, "event", None) == "feedback_attachment_collected"
    ]
    assert any(getattr(r, "attachment_kind", None) == "original_image" for r in attachment_logs)
    assert any(getattr(r, "attachment_kind", None) == "final_artifact" for r in attachment_logs)


def test_collect_sync_attachments_preserves_legacy_multi_lut_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-select legacy LUT reports keep every selected LUT.

    传统多选 LUT 的反馈包必须保留所有选中 LUT。
    """

    repo_root = tmp_path / "repo"
    lut_root = repo_root / "lut-preset"
    custom_lut = lut_root / "Custom" / "CustomA.json"
    preset_lut = lut_root / "Preset" / "PresetB.npy"
    custom_lut.parent.mkdir(parents=True)
    preset_lut.parent.mkdir(parents=True)
    custom_lut.write_bytes(b'{"color_mode":"4-Color"}')
    preset_lut.write_bytes(b"LUT-NPY")
    monkeypatch.setattr("api.feedback_assembler.REPO_ROOT", repo_root)
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(lut_root))
    monkeypatch.setattr(
        LUTManager,
        "get_lut_path",
        staticmethod(
            lambda name: {
                "CustomA": str(custom_lut),
                "PresetB": str(preset_lut),
            }.get(name)
        ),
    )

    ticket_dir = tmp_path / "LUM-20260707-001"
    ticket_dir.mkdir()
    payload: dict[str, Any] = {
        "ticket_id": "LUM-20260707-001",
        "context": {
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "CustomA",
            "lut_names": ["CustomA", "PresetB"],
        },
    }

    result = collect_sync_attachments(
        ticket_dir=ticket_dir,
        payload=payload,
        file_registry=_MockFileRegistry({}),
        now=now_beijing(),
    )

    assert result.lut["status"] == "attached"
    assert result.lut["kind"] == "multiple"
    assert result.lut["names"] == ["CustomA", "PresetB"]
    assert [item["name"] for item in result.lut["items"]] == ["CustomA", "PresetB"]
    assert result.lut["items"][0]["status"] == "attached"
    assert result.lut["items"][0]["filename"] == "lut_1.json"
    assert (ticket_dir / "lut_1.json").read_bytes() == b'{"color_mode":"4-Color"}'
    assert result.lut["items"][1]["status"] == "attached"
    assert (ticket_dir / "lut_2.npy").read_bytes() == b"LUT-NPY"
    assert result.lut["items"][1]["preset_relative_path"] == "lut-preset/Preset/PresetB.npy"


def test_collect_sync_attachments_preserves_missing_legacy_multi_lut_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed existing/missing legacy LUTs keep per-item diagnostics.

    传统多选 LUT 部分缺失时保留逐项诊断，不退化为收集崩溃。
    """

    repo_root = tmp_path / "repo"
    lut_root = repo_root / "lut-preset"
    existing_lut = lut_root / "Custom" / "Existing.json"
    existing_lut.parent.mkdir(parents=True)
    existing_lut.write_bytes(b'{"color_mode":"4-Color"}')
    monkeypatch.setattr("api.feedback_assembler.REPO_ROOT", repo_root)
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(lut_root))
    monkeypatch.setattr(
        LUTManager,
        "get_lut_path",
        staticmethod(lambda name: str(existing_lut) if name == "Existing" else None),
    )

    ticket_dir = tmp_path / "LUM-20260707-002"
    ticket_dir.mkdir()
    payload: dict[str, Any] = {
        "ticket_id": "LUM-20260707-002",
        "context": {
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "Existing",
            "lut_names": ["Existing", "Missing"],
        },
    }

    result = collect_sync_attachments(
        ticket_dir=ticket_dir,
        payload=payload,
        file_registry=_MockFileRegistry({}),
        now=now_beijing(),
    )

    assert result.lut["status"] == "partial"
    assert result.lut["kind"] == "multiple"
    assert result.lut["names"] == ["Existing", "Missing"]
    assert result.lut["error_type"] == "PartialLutCollection"
    assert result.lut["items"][0]["status"] == "attached"
    assert result.lut["items"][0]["filename"] == "lut_1.json"
    assert (ticket_dir / "lut_1.json").read_bytes() == b'{"color_mode":"4-Color"}'
    assert result.lut["items"][1]["status"] == "unavailable"
    assert result.lut["items"][1]["name"] == "Missing"
    assert result.lut["items"][1]["kind"] is None
    assert result.lut["items"][1]["filename"] is None


def test_collect_sync_attachments_marks_copy_failures_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    image_path = src_dir / "hello.png"
    image_path.write_bytes(b"PNGDATA")
    artifact_path = src_dir / "model.3mf"
    artifact_path.write_bytes(_project_bytes(b"3MFDATA"))

    registry = _MockFileRegistry(
        {
            "sess-report": {
                "img": _make_entry(str(image_path), "hello.png", created_at=1.0),
                "final": _make_entry(str(artifact_path), "model.3mf", created_at=2.0),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260619-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-001",
        "context": {
            "active_original_image_ref": {"session_id": "sess-report"},
            "active_final_artifact_ref": {
                "session_id": "sess-report",
                "artifact_type": "3mf",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    def _fail_ticket_attachment_copy(
        src: str | os.PathLike[str],
        dst: str | os.PathLike[str],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        del src, args, kwargs
        if Path(dst).name in {"original.png", "final.3mf"}:
            raise OSError("disk full")

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_ticket_attachment_copy)

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.original_image["status"] == "failed"
    assert result.original_image["filename"] is None
    assert result.original_image["error_type"] == "OSError"
    assert result.original_image["error_message"] == "Original image could not be saved."
    assert result.final_artifact["status"] == "failed"
    assert result.final_artifact["filename"] is None
    assert result.final_artifact["error_type"] == "OSError"
    assert result.final_artifact["error_message"] == "Final artifact could not be saved."
    assert not (ticket_dir / "original.png").exists()
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_sync_attachments_marks_copy_failures_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    image_path = src_dir / "hello.png"
    image_path.write_bytes(b"PNGDATA")
    artifact_path = src_dir / "model.3mf"
    artifact_path.write_bytes(_project_bytes(b"3MFDATA"))
    registry = _MockFileRegistry(
        {
            "sess-report": {
                "img": _make_entry(str(image_path), "hello.png", created_at=1.0),
                "final": _make_entry(str(artifact_path), "model.3mf", created_at=2.0),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260619-008"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-008",
        "context": {
            "active_original_image_ref": {"session_id": "sess-report"},
            "active_final_artifact_ref": {
                "session_id": "sess-report",
                "artifact_type": "3mf",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    def _fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_copy)

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.original_image["status"] == "failed"
    assert result.original_image["error_type"] == "OSError"
    assert result.final_artifact["status"] == "failed"
    assert result.final_artifact["error_type"] == "OSError"
    assert not (ticket_dir / "original.png").exists()
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_sync_attachments_tolerates_malformed_context(
    tmp_path: Path,
) -> None:
    ticket_dir = tmp_path / "LUM-20260619-010"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-010",
        "context": "bad-context",
    }

    result = collect_sync_attachments(
        ticket_dir,
        payload,
        _MockFileRegistry({}),
        now_beijing(),
    )

    assert result.original_image["status"] == "not_applicable"
    assert result.final_artifact["status"] == "not_applicable"
    assert result.lut["status"] == "not_applicable"


def test_finalize_ticket_async_marks_missing_declared_attachments_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-002"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-002",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "source_version": "legacy",
            "lut_name": None,
            "active_original_image_ref": {"session_id": "sess-report"},
            "active_final_artifact_ref": {
                "session_id": "sess-report",
                "artifact_type": "3mf",
                "download_url": "/api/files/missing-final",
            },
        },
        "attachments": {
            "original_image": {
                "status": "unavailable_after_cleanup",
                "filename": None,
                "source_session_id": "sess-report",
            },
            "final_artifact": {
                "status": "expired_ttl",
                "filename": None,
                "source_session_id": "sess-report",
                "artifact_type": "3mf",
            },
            "lut": {"status": "not_applicable"},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "partial_failed"
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


def test_finalize_ticket_async_marks_disk_path_only_final_ref_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-016"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-016",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "source_version": "legacy",
            "lut_name": None,
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": None,
                "download_url": None,
                "artifact_type": "3mf",
                "disk_path": "/nonexistent/path/model.3mf",
            },
        },
        "attachments": {
            "original_image": {"status": "not_applicable", "filename": None},
            "final_artifact": {
                "status": "expired_ttl",
                "filename": None,
                "artifact_type": "3mf",
            },
            "lut": {"status": "not_applicable", "filename": None},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "partial_failed"


def test_finalize_ticket_async_leaves_unreferenced_attachments_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-003"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-003",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "source_version": "legacy",
            "lut_name": None,
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
        },
        "attachments": {
            "original_image": {"status": "not_applicable", "filename": None},
            "final_artifact": {"status": "not_applicable", "filename": None},
            "lut": {"status": "not_applicable", "filename": None},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "done"


def test_finalize_ticket_async_accepts_preset_lut_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    preset_lut = repo_root / "lut-preset" / "BIQU" / "preset.json"
    preset_lut.write_bytes(b"PRESET_LUT_BYTES")
    ticket_dir = tmp_path / "LUM-20260619-006"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-006",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "BIQU - preset",
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
        },
        "attachments": {
            "original_image": {"status": "not_applicable", "filename": None},
            "final_artifact": {"status": "not_applicable", "filename": None},
            "lut": {
                "status": "preset_reference_only",
                "kind": "preset",
                "name": "BIQU - preset",
                "preset_relative_path": "lut-preset/BIQU/preset.json",
                "filename": None,
                "sha256": "daea61c337077769f11b77306bc80a91baf0aef78aaae60fec3e9f4739231c93",
                "size_bytes": len(b"PRESET_LUT_BYTES"),
                "metadata": {},
            },
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    try:
        asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))
    finally:
        LUTManager.invalidate_preset_cache()

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "done"


@pytest.mark.parametrize("preset_exists", [True, False])
@pytest.mark.parametrize("mutation", ["unchanged", "missing", "changed", "symlink"])
def test_shared_cloud_copy_survives_full_ticket_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    preset_exists: bool, mutation: str,
) -> None:
    _disable_feedback_upload(monkeypatch)
    _use_feedback_lut_repo(monkeypatch, tmp_path)
    if not preset_exists:
        monkeypatch.setattr("api.feedback_assembler.REPO_ROOT", tmp_path / "missing-repo")
        monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "missing-repo/lut-preset"))
    cloud = tmp_path / "launcher" / "cloud"
    cloud.mkdir(parents=True)
    source = cloud / "sample.json"
    original = b"SHARED_CLOUD"
    source.write_bytes(original)
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud))
    LUTManager.invalidate_preset_cache()
    ticket_dir = tmp_path / "LUM-20260910-cloud"
    ticket_dir.mkdir()
    payload = {
        "schema_version": 3,
        "ticket_id": ticket_dir.name,
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "active_tab": "converter", "source_version": "legacy",
            "lut_name": "Cloud - sample",
            "active_original_image_ref": None, "active_final_artifact_ref": None,
        },
    }
    try:
        collected = collect_sync_attachments(ticket_dir, payload, _MockFileRegistry({}), now_beijing())
        payload["attachments"] = {
            "original_image": collected.original_image,
            "final_artifact": collected.final_artifact,
            "lut": collected.lut,
        }
        ticket_json = ticket_dir / "ticket.json"
        ticket_json.write_text(json.dumps(payload), encoding="utf-8")
        if mutation == "missing":
            source.unlink()
        elif mutation == "changed":
            source.write_bytes(b"CHANGED_LUT!")
        elif mutation == "symlink":
            outside = tmp_path / "outside.json"
            outside.write_bytes(original)  # Matching bytes must not bypass containment.
            source.unlink()
            try:
                source.symlink_to(outside)
            except OSError:
                pytest.skip("File symlink creation is unavailable")
        asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))
        finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
        attachment = finalized["attachments"]["lut"]
        assert finalized["assembly_status"] == "done"
        assert attachment["status"] == "attached"
        assert attachment["preset_relative_path"] == "lut-preset/Cloud/sample.json"
        assert str(cloud) not in ticket_json.read_text(encoding="utf-8")
        assert (ticket_dir / "lut.json").read_bytes() == original
    finally:
        LUTManager.invalidate_preset_cache()


def test_finalize_ticket_async_does_not_require_lut_for_native_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-014"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-014",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "active_tab": "converter",
            "source_version": "native",
            "lut_name": "native-summary",
            "selected_native_db_names": ["BIQU"],
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
        },
        "attachments": {
            "original_image": {"status": "not_applicable", "filename": None},
            "final_artifact": {"status": "not_applicable", "filename": None},
            "lut": {"status": "not_applicable", "filename": None},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "done"


def test_finalize_ticket_async_marks_invalid_attachment_section_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-007"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-007",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "source_version": "legacy",
            "lut_name": None,
            "active_original_image_ref": {"session_id": "sess-bad"},
            "active_final_artifact_ref": None,
        },
        "attachments": {
            "original_image": "bad-manifest",
            "final_artifact": {"status": "not_applicable", "filename": None},
            "lut": {"status": "not_applicable", "filename": None},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "partial_failed"
    assert finalized["attachments"]["original_image"]["status"] == "failed"
    assert finalized["attachments"]["original_image"]["error_type"] == (
        "InvalidAttachmentManifest"
    )


@pytest.mark.parametrize("legacy_digest", [None, "retired-digest"])
def test_finalize_ticket_accepts_local_attachments_without_content_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_digest: str | None,
) -> None:
    """Local finalization accepts new manifests and ignores old digest metadata.
    本地终结流程接受新清单，并忽略旧摘要元数据。
    """
    _disable_feedback_upload(monkeypatch)
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    source_lut = repo_root / "lut-preset" / "Custom" / "safe.json"
    source_lut.write_bytes(b"CUSTOM_LUT_BYTES")
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"PNGDATA")
    artifact_path = tmp_path / "output.3mf"
    artifact_path.write_bytes(_project_bytes(b"3MFDATA"))
    registry = _MockFileRegistry({
        "session": {
            "image": _make_entry(str(image_path), image_path.name, created_at=1.0),
            "final": _make_entry(str(artifact_path), artifact_path.name, created_at=2.0),
        },
    })
    ticket_dir = tmp_path / "LUM-20261003-local"
    ticket_dir.mkdir()
    payload = {
        "schema_version": 3,
        "ticket_id": ticket_dir.name,
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "active_tab": "converter", "source_version": "legacy",
            "lut_name": "Custom - safe",
            "active_original_image_ref": {"session_id": "session"},
            "active_final_artifact_ref": {"session_id": "session", "artifact_type": "3mf"},
        },
    }
    try:
        collected = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())
        payload["attachments"] = {
            "original_image": collected.original_image,
            "final_artifact": collected.final_artifact,
            "lut": collected.lut,
        }
        for attachment in payload["attachments"].values():
            assert "sha256" not in attachment
            if legacy_digest is not None:
                attachment["sha256"] = legacy_digest
        ticket_json = ticket_dir / "ticket.json"
        ticket_json.write_text(json.dumps(payload), encoding="utf-8")

        asyncio.run(finalize_ticket_async(ticket_dir, registry))

        finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
        assert finalized["assembly_status"] == "done"
        for key in ("original_image", "final_artifact", "lut"):
            assert finalized["attachments"][key]["status"] == "attached"
        assert (ticket_dir / "original.png").read_bytes() == image_path.read_bytes()
        assert (ticket_dir / "final.3mf").read_bytes() == artifact_path.read_bytes()
        assert (ticket_dir / "lut.json").read_bytes() == source_lut.read_bytes()
        assert "sha256" not in (ticket_dir / "index.md").read_text(encoding="utf-8")
    finally:
        LUTManager.invalidate_preset_cache()


def test_finalize_ticket_async_marks_invalid_attached_manifests_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    preset_lut = repo_root / "lut-preset" / "BIQU" / "preset.json"
    preset_lut.write_bytes(b"PRESET_LUT_BYTES")
    ticket_dir = tmp_path / "LUM-20260619-017"
    ticket_dir.mkdir()
    (ticket_dir / "original.png").write_bytes(b"PNGDATA")
    (ticket_dir / "final.3mf").write_bytes(b"3MFDATA")
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-017",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": {
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "BIQU - preset",
            "active_original_image_ref": {"session_id": "sess-bad"},
            "active_final_artifact_ref": {
                "session_id": "sess-bad",
                "artifact_type": "3mf",
            },
        },
        "attachments": {
            "original_image": {
                "status": "attached",
                "filename": "original.png",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "mime_type": "image/png",
            },
            "final_artifact": {
                "status": "attached",
                "filename": "final.3mf",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "artifact_type": "3mf",
            },
            "lut": {
                "status": "preset_reference_only",
                "kind": "preset",
                "name": "BIQU - preset",
                "preset_relative_path": "lut-preset/BIQU/preset.json",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "metadata": {},
            },
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    try:
        asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))
    finally:
        LUTManager.invalidate_preset_cache()

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["assembly_status"] == "partial_failed"
    assert finalized["attachments"]["original_image"]["status"] == "failed"
    assert finalized["attachments"]["original_image"]["error_type"] == (
        "InvalidAttachmentManifest"
    )
    assert finalized["attachments"]["final_artifact"]["status"] == "failed"
    assert finalized["attachments"]["final_artifact"]["error_type"] == (
        "InvalidAttachmentManifest"
    )
    assert finalized["attachments"]["lut"]["status"] == "failed"
    assert finalized["attachments"]["lut"]["error_type"] == (
        "InvalidAttachmentManifest"
    )


def test_finalize_ticket_async_tolerates_malformed_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_feedback_upload(monkeypatch)
    ticket_dir = tmp_path / "LUM-20260619-011"
    ticket_dir.mkdir()
    ticket_json = ticket_dir / "ticket.json"
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260619-011",
        "received_at_cst": now_beijing().isoformat(),
        "assembly_status": "in_progress",
        "context": "bad-context",
        "attachments": {
            "original_image": {"status": "not_applicable", "filename": None},
            "final_artifact": {"status": "not_applicable", "filename": None},
            "lut": {"status": "not_applicable", "filename": None},
        },
    }
    ticket_json.write_text(json.dumps(payload), encoding="utf-8")

    asyncio.run(finalize_ticket_async(ticket_dir, _MockFileRegistry({})))

    finalized = json.loads(ticket_json.read_text(encoding="utf-8"))
    assert finalized["context"] == {}
    assert finalized["assembly_status"] == "done"
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


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
    assert result.original_image["capture_source"] == "session_store"
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
    assert result.original_image["capture_source"] == "file_registry"
    assert (ticket_dir / "original.png").read_bytes() == b"REGISTRY"


def test_collect_original_image_stale_registry_falls_back_to_session_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    session_image = temp_root / "session.png"
    session_image.write_bytes(b"SESSION")
    monkeypatch.setattr("api.feedback_assembler.TEMP_DIR", str(temp_root))

    registry = _MockFileRegistry(
        {
            "sess-orig": {
                "stale": _make_entry(
                    str(tmp_path / "missing.png"),
                    "missing.png",
                    created_at=1.0,
                ),
            },
        }
    )
    session_store = _MockSessionStore({"sess-orig": {"image_path": str(session_image)}})
    ticket_dir = tmp_path / "LUM-20260619-012"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-012",
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
    assert result.original_image["capture_source"] == "session_store"
    assert (ticket_dir / "original.png").read_bytes() == b"SESSION"


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


def test_collect_sync_attachments_lut_is_noop_for_native_mode(
    tmp_path: Path,
) -> None:
    registry = _MockFileRegistry({})
    ticket_dir = tmp_path / "LUM-20260619-013"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-013",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "active_tab": "converter",
            "source_version": "native",
            "lut_name": "native-summary",
            "selected_native_db_names": ["BIQU"],
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.lut["status"] == "not_applicable"


def _use_feedback_lut_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    repo_root = tmp_path / "repo"
    preset_root = repo_root / "lut-preset"
    (preset_root / "Custom").mkdir(parents=True)
    (preset_root / "BIQU").mkdir(parents=True)
    monkeypatch.setattr("api.feedback_assembler.REPO_ROOT", repo_root)
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(preset_root))
    LUTManager.invalidate_preset_cache()
    return repo_root


def test_collect_lut_rejects_path_traversal_lut_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    (repo_root / "private_config.json").write_bytes(b"ROOT_CONFIG")
    ticket_dir = tmp_path / "LUM-20260618-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260618-001",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": "Custom/../../private_config",
        },
    }

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "failed"
    assert result.lut["error_type"] == "InvalidLutName"
    assert result.lut["error_message"] == "LUT could not be saved."
    assert not (ticket_dir / "lut.json").exists()


def test_collect_lut_accepts_custom_display_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    safe_lut = repo_root / "lut-preset" / "Custom" / "safe.json"
    safe_lut.write_bytes(b"SAFE_CUSTOM_LUT")
    ticket_dir = tmp_path / "LUM-20260618-002"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260618-002",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": "Custom - safe",
        },
    }

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "attached"
    assert result.lut["kind"] == "custom"
    assert result.lut["filename"] == "lut.json"
    assert (ticket_dir / "lut.json").read_bytes() == b"SAFE_CUSTOM_LUT"


def test_collect_lut_accepts_launcher_shared_custom_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_feedback_lut_repo(monkeypatch, tmp_path)
    shared_custom_root = tmp_path / "launcher-data" / "luts" / "custom"
    shared_custom_root.mkdir(parents=True)
    shared_lut = shared_custom_root / "safe.json"
    shared_lut.write_bytes(b"SHARED_CUSTOM_LUT")
    monkeypatch.setenv("LUMINA_CUSTOM_LUT_DIR", str(shared_custom_root))
    LUTManager.invalidate_preset_cache()
    ticket_dir = tmp_path / "LUM-20260903-001"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260903-001",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": "Custom - safe",
        },
    }

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "attached"
    assert result.lut["kind"] == "custom"
    assert result.lut["filename"] == "lut.json"
    assert (ticket_dir / "lut.json").read_bytes() == b"SHARED_CUSTOM_LUT"


@pytest.mark.parametrize("preset_exists", [True, False])
@pytest.mark.parametrize("escape", [False, True])
def test_shared_cloud_lut_lookup_preserves_attachment_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    preset_exists: bool, escape: bool,
) -> None:
    from api import feedback_assembler as assembler

    _use_feedback_lut_repo(monkeypatch, tmp_path)
    if not preset_exists:
        monkeypatch.setattr(assembler, "REPO_ROOT", tmp_path / "missing-repo")
        monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(tmp_path / "missing-repo/lut-preset"))
    cloud = tmp_path / "shared-cloud"
    cloud.mkdir()
    source = cloud / "sample.json"
    if escape:
        outside = tmp_path / "outside.json"
        outside.write_bytes(b"PRIVATE")
        try:
            source.symlink_to(outside)
        except OSError:
            pytest.skip("File symlink creation is unavailable")
    else:
        source.write_bytes(b"SHARED_CLOUD")
    monkeypatch.setenv("LUMINA_CLOUD_LUT_DIR", str(cloud))
    LUTManager.invalidate_preset_cache()
    try:
        assert LUTManager.get_lut_path("Cloud - sample") is not None
        found = assembler._find_lut_file("Cloud - sample")
        assert found == (None if escape else source.resolve())
        ticket = tmp_path / "ticket"
        ticket.mkdir()
        attachment = assembler._collect_lut(ticket, {"lut_name": "Cloud - sample"})
        assert attachment["status"] == ("unavailable" if escape else "attached")
        if escape:
            assert attachment["filename"] is None
            assert not list(ticket.iterdir())
        else:
            assert (ticket / attachment["filename"]).read_bytes() == b"SHARED_CLOUD"
    finally:
        LUTManager.invalidate_preset_cache()


def test_collect_lut_marks_custom_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    safe_lut = repo_root / "lut-preset" / "Custom" / "safe.json"
    safe_lut.write_bytes(b"SAFE_CUSTOM_LUT")
    ticket_dir = tmp_path / "LUM-20260619-004"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-004",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "Custom - safe",
        },
    }

    def _fail_lut_copy(
        src: str | os.PathLike[str],
        dst: str | os.PathLike[str],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        del src, args, kwargs
        if Path(dst).name == "lut.json":
            raise OSError("disk full")

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_lut_copy)

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "failed"
    assert result.lut["kind"] == "custom"
    assert result.lut["name"] == "Custom - safe"
    assert result.lut["filename"] is None
    assert result.lut["error_type"] == "OSError"
    assert result.lut["error_message"] == "copy failed"
    assert not (ticket_dir / "lut.json").exists()


def test_collect_lut_marks_custom_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    safe_lut = repo_root / "lut-preset" / "Custom" / "safe.json"
    safe_lut.write_bytes(b"SAFE_CUSTOM_LUT")
    ticket_dir = tmp_path / "LUM-20260619-009"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-009",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "active_tab": "converter",
            "source_version": "legacy",
            "lut_name": "Custom - safe",
        },
    }

    def _fail_copy(_source: Path, _destination: Path) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_copy)

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "failed"
    assert result.lut["kind"] == "custom"
    assert result.lut["error_type"] == "OSError"
    assert result.lut["error_message"] == "copy failed"
    assert not (ticket_dir / "lut.json").exists()


def test_collect_lut_accepts_nested_preset_display_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = _use_feedback_lut_repo(monkeypatch, tmp_path)
    preset_lut = repo_root / "lut-preset" / "BIQU" / "必趣&PLAGO&6色RYBWGK.json"
    preset_lut.write_bytes(b"BIQU_PRESET_LUT")
    ticket_dir = tmp_path / "LUM-20260618-003"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260618-003",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "source_version": "legacy",
            "lut_name": "BIQU - 必趣&PLAGO&6色RYBWGK",
        },
    }

    try:
        result = collect_sync_attachments(
            ticket_dir,
            payload,
            _MockFileRegistry({}),
            now_beijing(),
        )
    finally:
        LUTManager.invalidate_preset_cache()

    assert result.lut["status"] == "attached"
    assert result.lut["kind"] == "preset"
    assert result.lut["preset_relative_path"] == (
        "lut-preset/BIQU/必趣&PLAGO&6色RYBWGK.json"
    )
    assert (ticket_dir / "lut.json").read_bytes() == b"BIQU_PRESET_LUT"


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


def test_collect_final_artifact_disk_path_only_marks_declared_artifact_expired(
    tmp_path: Path,
) -> None:
    registry = _MockFileRegistry({})
    ticket_dir = tmp_path / "LUM-20260619-015"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-015",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": None,
                "download_url": None,
                "artifact_type": "3mf",
                "disk_path": "/nonexistent/path/model.3mf",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert result.final_artifact["artifact_type"] == "3mf"
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_final_artifact_uses_download_url_for_ttl_zip(
    tmp_path: Path,
) -> None:
    """A large-format TTL ZIP can be copied by its exact /api/files URL.

    大画幅 ZIP 可能不挂在当前业务 session 下，应能按下载 URL 精确复制。
    """
    zip_path = tmp_path / "large_format_tiles.zip"
    project = _project_bytes(b"GEOMETRY", {
        "printhost_apikey": "fake-secret", "layer_height": "0.16",
        "nested": [{"PrInThOsT_password": "fake-password", "wall_loops": "3"}],
    })
    with zipfile.ZipFile(zip_path, "w") as batch:
        batch.writestr("tiles/model.3mf", project)
        batch.writestr("preview.png", b"PREVIEW")
    original_bytes = zip_path.read_bytes()
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
    assert zip_path.read_bytes() == original_bytes
    with zipfile.ZipFile(ticket_dir / "final.zip") as batch:
        assert batch.read("preview.png") == b"PREVIEW"
        with zipfile.ZipFile(io.BytesIO(batch.read("tiles/model.3mf"))) as project:
            assert project.read("3D/3dmodel.model") == b"GEOMETRY"
            assert json.loads(project.read("Metadata/project_settings.config")) == {
                "layer_height": "0.16", "printhost_apikey": "fake-secret", "nested": [{"PrInThOsT_password": "fake-password", "wall_loops": "3"}],
            }


def test_collect_final_artifact_download_url_copy_failure_is_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    ticket_dir = tmp_path / "LUM-20260619-005"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260619-005",
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

    def _fail_final_copy(
        src: str | os.PathLike[str],
        dst: str | os.PathLike[str],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        del src, args, kwargs
        if Path(dst).name == "final.zip":
            raise OSError("disk full")

    with monkeypatch.context() as copying:
        copying.setattr("api.feedback_assembler.shutil.copy2", _fail_final_copy)
        result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "failed"
    assert result.final_artifact["filename"] is None
    assert result.final_artifact["artifact_type"] == "zip"
    assert result.final_artifact["error_type"] == "OSError"
    assert result.final_artifact["error_message"] == "Final artifact could not be saved."
    assert not (ticket_dir / "final.zip").exists()

    from api.feedback_hosted import build_ticket_bundle

    damaged = _project_bytes(
        b"GEOMETRY", {"printhost_apikey": "fake-secret", "layer_height": "0.2"},
        damaged_metadata=True,
    )
    batch = io.BytesIO()
    with zipfile.ZipFile(batch, "w") as archive:
        archive.writestr("tiles/model.3mf", damaged)
    for suffix, content in ((".3mf", damaged), (".zip", batch.getvalue())):
        source = tmp_path / f"damaged{suffix}"
        source.write_bytes(content)
        case_registry = _MockFileRegistry({
            "sess-current": {
                "damaged-file-id": _make_entry(str(source), source.name, created_at=10.0),
            },
        })
        for route in ("download_url", "session"):
            case_dir = tmp_path / f"damaged-{suffix[1:]}-{route}"
            case_dir.mkdir()
            payload["context"]["active_final_artifact_ref"].update({
                "artifact_type": suffix[1:],
                "download_url": "/api/files/damaged-file-id" if route == "download_url" else None,
            })
            failed = collect_sync_attachments(case_dir, payload, case_registry, now_beijing())
            assert failed.final_artifact["status"] == "attached"
            assert source.read_bytes() == content
            assert (case_dir / f"final{suffix}").read_bytes() == content
            payload["attachments"] = {"final_artifact": failed.final_artifact}
            assert len(build_ticket_bundle(case_dir, payload).files) == 1


def test_collect_final_artifact_prefers_download_url_over_stale_session_entry(
    tmp_path: Path,
) -> None:
    """The exact download URL represents the user's current final artifact.

    精确下载链接代表用户当前看到的最终产物，不能被同 session 下的旧产物覆盖。
    """
    stale_path = tmp_path / "stale_model.3mf"
    stale_path.write_bytes(b"OLD_3MF")
    current_path = tmp_path / "current_tiles.zip"
    current_path.write_bytes(_batch_bytes(b"CURRENT_ZIP"))
    registry = _MockFileRegistry(
        {
            "sess-current": {
                "old-3mf-id": _make_entry(
                    str(stale_path),
                    "stale_model.3mf",
                    created_at=8.0,
                ),
            },
            "ttl-owner": {
                "current-zip-id": _make_entry(
                    str(current_path),
                    "current_tiles.zip",
                    created_at=9.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260524-009"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260524-009",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-current",
                "download_url": "/api/files/current-zip-id",
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
    assert result.final_artifact["source_session_id"] == "sess-current"
    assert result.final_artifact["history_count"] == 1
    assert (ticket_dir / "final.zip").read_bytes() == current_path.read_bytes()
    assert not (ticket_dir / "final.3mf").exists()


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
    registry_3mf.write_bytes(_project_bytes(b"REGISTRY_3MF"))

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
        assert (ticket_dir / "final.3mf").read_bytes() == registry_3mf.read_bytes()
    finally:
        disk_3mf.unlink(missing_ok=True)


def test_collect_final_artifact_stale_registry_rejects_disk_path_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale FileRegistry hit must not authorize client disk_path fallback.

    FileRegistry 命中但磁盘文件已清理时，客户端 disk_path 仍不能授权复制。
    """
    monkeypatch.setattr("api.feedback_assembler.REPO_ROOT", tmp_path)

    output_dir = tmp_path / "output" / "models"
    output_dir.mkdir(parents=True)
    fallback_3mf = output_dir / "fallback_model.3mf"
    fallback_3mf.write_bytes(b"FALLBACK_3MF")

    registry = _MockFileRegistry(
        {
            "sess-final": {
                "stale": _make_entry(
                    str(tmp_path / "missing_registry_model.3mf"),
                    "missing_registry_model.3mf",
                    created_at=10.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260616-020"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260616-020",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-final",
                "artifact_type": "3mf",
                "disk_path": str(fallback_3mf),
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "expired_ttl"
    assert result.final_artifact["filename"] is None
    assert not (ticket_dir / "final.3mf").exists()


def test_collect_final_artifact_stale_registry_falls_back_to_download_url(
    tmp_path: Path,
) -> None:
    """A stale session artifact should not block exact download URL recovery.

    session 里的旧产物条目失效时，不应阻断精确下载 URL 回收。
    """
    stale_path = tmp_path / "missing_session_model.3mf"
    ttl_zip_path = tmp_path / "large_format_tiles.zip"
    ttl_zip_path.write_bytes(_batch_bytes(b"TTL_ZIP"))
    registry = _MockFileRegistry(
        {
            "sess-final": {
                "stale": _make_entry(
                    str(stale_path),
                    "missing_session_model.3mf",
                    created_at=10.0,
                ),
            },
            "ttl-owner": {
                "zip-file-id": _make_entry(
                    str(ttl_zip_path),
                    "large_format_tiles.zip",
                    created_at=11.0,
                ),
            },
        }
    )
    ticket_dir = tmp_path / "LUM-20260616-021"
    ticket_dir.mkdir()
    payload = {
        "ticket_id": "LUM-20260616-021",
        "context": {
            "active_original_image_ref": None,
            "active_final_artifact_ref": {
                "session_id": "sess-final",
                "download_url": "/api/files/zip-file-id?download=1",
                "artifact_type": "zip",
            },
            "source_version": "legacy",
            "lut_name": None,
        },
    }

    result = collect_sync_attachments(ticket_dir, payload, registry, now_beijing())

    assert result.final_artifact["status"] == "attached"
    assert result.final_artifact["filename"] == "final.zip"
    assert result.final_artifact["artifact_type"] == "zip"
    assert (ticket_dir / "final.zip").read_bytes() == ttl_zip_path.read_bytes()
