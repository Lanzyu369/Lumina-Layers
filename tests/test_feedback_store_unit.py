"""Unit tests for feedback dump storage."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def _payload(session_id: str | None) -> dict[str, object]:
    return {
        "description": "The preview failed after clicking generate.",
        "user_email": None,
        "context": {
            "active_session_ids": {
                "converter": session_id,
                "single_stage": None,
            },
            "language": "en",
        },
        "screenshot_data_url": None,
    }


def test_dump_bug_report_creates_utf8_json_with_sanitized_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.feedback_store import dump_bug_report

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path / "feedback"))

    path, ticket_id = dump_bug_report(_payload("../bad\\session\0id"))

    assert path.parent == tmp_path / "feedback"
    assert path.exists()
    assert ticket_id == "___bad_s"
    assert re.match(r"^\d{8}T\d{6}Z____bad_session_id\.json$", path.name)
    assert ".." not in path.name
    assert "\\" not in path.name
    assert "\0" not in path.name
    assert json.loads(path.read_text(encoding="utf-8")) == _payload("../bad\\session\0id")


def test_dump_bug_report_uses_converter_session_before_single_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from api.feedback_store import dump_bug_report

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path))
    payload = _payload("converter-session-1234567890")
    payload["context"] = {
        "active_session_ids": {
            "converter": "converter-session-1234567890",
            "single_stage": "single-stage-session",
        }
    }

    path, ticket_id = dump_bug_report(payload)

    assert ticket_id == "converte"
    assert path.name.endswith("_converter-session-1234567890.json")


def test_dump_bug_report_falls_back_to_uuid_when_no_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import api.feedback_store as feedback_store

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        feedback_store,
        "uuid4",
        lambda: type("UUIDStub", (), {"hex": "abcdef1234567890fedcba"})(),
    )

    path, ticket_id = feedback_store.dump_bug_report(_payload(None))

    assert ticket_id == "abcdef12"
    assert path.name.endswith("_abcdef1234567890.json")
