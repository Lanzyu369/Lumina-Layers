"""Unit tests for ``scripts.load_bug_repro``.

验证 load_bug_repro CLI：目录查找、附件复制、materials.zip 解压、缺失附件
降级、repro_manifest.md 生成。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

# Import the CLI module by path so pytest picks it up without package
# metadata. scripts/ is already added to sys.path by the module itself.
from scripts.load_bug_repro import load_bug_repro


def _write_ticket(root: Path, ticket_id: str, partial: bool = False) -> Path:
    month = f"{ticket_id.split('-')[1][:4]}-{ticket_id.split('-')[1][4:6]}"
    ticket_dir = root / month / ticket_id
    ticket_dir.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "ticket_id": ticket_id,
        "received_at_cst": "2026-05-11T14:03:22+08:00",
        "description": "test ticket",
        "context": {
            "action_history": [
                {
                    "timestamp": 1747000000000,
                    "action_type": "upload_image",
                    "snapshot": {},
                },
                {
                    "timestamp": 1747000010000,
                    "action_type": "api_error",
                    "error": {
                        "status_code": 500,
                        "path": "/api/converter/generate",
                        "error_message": "oops",
                    },
                },
            ]
        },
    }
    (ticket_dir / "ticket.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if not partial:
        (ticket_dir / "original.png").write_bytes(b"PNG")
        (ticket_dir / "final.3mf").write_bytes(b"3MF")
        (ticket_dir / "lut.npy").write_bytes(b"LUT")
        (ticket_dir / "screenshot.png").write_bytes(b"SHOT")
        # Real zip so the extraction path can unpack it.
        with zipfile.ZipFile(ticket_dir / "materials.zip", "w") as zf:
            zf.writestr("BrandA/profile.json", b"{}")
    (ticket_dir / "index.md").write_text("# index", encoding="utf-8")
    (ticket_dir / "summary.txt").write_text("summary", encoding="utf-8")
    return ticket_dir


def test_load_bug_repro_copies_all_known_attachments(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    _write_ticket(feedback_root, "LUM-20260511-001")

    result = load_bug_repro(
        "LUM-20260511-001",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    assert result.repro_dir.is_dir()
    for name in (
        "original.png",
        "final.3mf",
        "lut.npy",
        "materials.zip",
        "screenshot.png",
        "ticket.json",
        "index.md",
        "summary.txt",
    ):
        assert (result.repro_dir / name).exists(), name
    assert result.attachments_missing == ["client_logs.jsonl"]


def test_load_bug_repro_locates_new_random_monthly_ticket(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    ticket_id = "LUM-202605-deadbeef"
    source_dir = _write_ticket(feedback_root, ticket_id)

    result = load_bug_repro(
        ticket_id,
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    assert result.source_dir == source_dir
    assert (result.repro_dir / "original.png").read_bytes() == b"PNG"


def test_load_bug_repro_extracts_materials_zip(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    _write_ticket(feedback_root, "LUM-20260511-002")

    result = load_bug_repro(
        "LUM-20260511-002",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    extracted = result.repro_dir / "materials" / "BrandA" / "profile.json"
    assert extracted.is_file()
    assert extracted.read_bytes() == b"{}"


def test_load_bug_repro_handles_partial_ticket(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    _write_ticket(feedback_root, "LUM-20260511-003", partial=True)

    result = load_bug_repro(
        "LUM-20260511-003",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    assert "ticket.json" in result.attachments_copied
    assert "index.md" in result.attachments_copied
    assert "summary.txt" in result.attachments_copied
    for missing_pattern in ("original.*", "final.*", "lut.*", "materials.zip", "screenshot.*"):
        assert missing_pattern in result.attachments_missing


def test_load_bug_repro_raises_when_ticket_missing(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    feedback_root.mkdir()
    with pytest.raises(FileNotFoundError):
        load_bug_repro(
            "LUM-20990101-999",
            feedback_root=feedback_root,
            repro_root=tmp_path / "repro_sessions",
        )


@pytest.mark.parametrize(
    "ticket_id",
    ["..", "LUM-202605-../../", "LUM-202605-DEADBEEF", "arbitrary-ticket"],
)
def test_load_bug_repro_rejects_invalid_ticket_ids_without_path_escape(
    tmp_path: Path,
    ticket_id: str,
) -> None:
    feedback_root = tmp_path / "feedback"
    feedback_root.mkdir()
    repro_root = tmp_path / "repro_sessions"

    with pytest.raises(FileNotFoundError):
        load_bug_repro(
            ticket_id,
            feedback_root=feedback_root,
            repro_root=repro_root,
        )

    assert not repro_root.exists()


def test_load_bug_repro_writes_manifest_with_actions(tmp_path: Path) -> None:
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    _write_ticket(feedback_root, "LUM-20260511-004")

    result = load_bug_repro(
        "LUM-20260511-004",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    manifest = result.manifest_path.read_text(encoding="utf-8")
    assert "Reproduction manifest" in manifest
    assert "upload_image" in manifest
    assert "api_error" in manifest
    assert "/api/converter/generate" in manifest
    assert "?repro_session=LUM-20260511-004" in manifest


def test_load_bug_repro_locates_ticket_by_scan_when_month_partition_mismatches(
    tmp_path: Path,
) -> None:
    """Tickets moved to a different month partition still resolve via scan."""
    feedback_root = tmp_path / "feedback"
    # Put the 2026-05 ticket into a 2025-01 partition on purpose.
    unusual = feedback_root / "2025-01" / "LUM-20260511-005"
    unusual.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260511-005",
        "received_at_cst": "2026-05-11T14:03:22+08:00",
        "description": "moved",
        "context": {},
    }
    (unusual / "ticket.json").write_text(json.dumps(payload), encoding="utf-8")

    result = load_bug_repro(
        "LUM-20260511-005",
        feedback_root=feedback_root,
        repro_root=tmp_path / "repro_sessions",
    )

    assert result.source_dir == unusual


def test_load_bug_repro_rejects_zip_slip_entries(tmp_path: Path) -> None:
    """Zip entries with ../../ paths do not write outside repro_root.

    zip 中包含 ../../evil.txt 的条目不会写到 repro_root 外。
    """
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    ticket_dir = feedback_root / "2026-05" / "LUM-20260511-010"
    ticket_dir.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260511-010",
        "received_at_cst": "2026-05-11T14:03:22+08:00",
        "description": "zip slip test",
        "context": {},
    }
    (ticket_dir / "ticket.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    # Create a malicious zip with a path-traversal entry.
    malicious_zip = ticket_dir / "materials.zip"
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
        zf.writestr("safe/good.txt", "ok")

    result = load_bug_repro(
        "LUM-20260511-010",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    # The evil file must NOT exist outside the repro dir.
    assert not (tmp_path / "evil.txt").exists()
    assert not (repro_root / "evil.txt").exists()
    # The safe file should have been extracted.
    safe_file = result.repro_dir / "materials" / "safe" / "good.txt"
    assert safe_file.is_file()
    assert safe_file.read_text() == "ok"


def test_load_bug_repro_handles_bad_zip_gracefully(tmp_path: Path) -> None:
    """A corrupt materials.zip does not crash load_bug_repro.

    损坏的 materials.zip 不会导致 load_bug_repro 崩溃。
    """
    feedback_root = tmp_path / "feedback"
    repro_root = tmp_path / "repro_sessions"
    ticket_dir = feedback_root / "2026-05" / "LUM-20260511-011"
    ticket_dir.mkdir(parents=True)
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260511-011",
        "received_at_cst": "2026-05-11T14:03:22+08:00",
        "description": "bad zip test",
        "context": {},
    }
    (ticket_dir / "ticket.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    # Write a corrupt zip file.
    (ticket_dir / "materials.zip").write_bytes(b"not a zip file at all")

    result = load_bug_repro(
        "LUM-20260511-011",
        feedback_root=feedback_root,
        repro_root=repro_root,
    )

    # Should not crash; materials directory may exist but be empty.
    assert result.repro_dir.is_dir()
    assert "materials.zip" in result.attachments_copied
