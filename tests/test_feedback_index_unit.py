"""Unit tests for ``api.feedback_index`` — index.md and summary.txt render.

验证工单索引渲染：字段完整时显示正确；缺失字段不抛；Chinese 保持可读。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.feedback_index import (
    generate_index_markdown,
    generate_summary_text,
)


def _sample_payload(**overrides):
    payload = {
        "schema_version": 3,
        "ticket_id": "LUM-20260511-001",
        "received_at_cst": "2026-05-11T14:03:22+08:00",
        "description": "耗材档案8色10层高保真导出3MF是经典墙",
        "user_email": "user@example.com",
        "context": {
            "active_tab": "converter",
            "source_version": "material",
            "color_mode": None,
            "lut_name": None,
            "selected_material_dir_names": ["BrandA", "BrandB"],
            "material_layer_count": 10,
            "material_layer_height_mm": 0.16,
            "material_backing_material_dir_name": "BrandA",
            "action_history": [
                {
                    "timestamp": 1747000000000,
                    "action_type": "upload_image",
                    "snapshot": {
                        "active_tab": "converter",
                        "source_version": "material",
                    },
                },
                {
                    "timestamp": 1747000010000,
                    "action_type": "color_mode_change",
                    "changed_fields": {
                        "color_mode": {"from": "6-Color", "to": "8-Color"}
                    },
                    "snapshot": {"active_tab": "converter"},
                },
                {
                    "timestamp": 1747000020000,
                    "action_type": "api_error",
                    "error": {
                        "status_code": 500,
                        "path": "/api/converter/generate",
                        "error_message": "internal server error",
                    },
                    "snapshot": {},
                },
            ],
            "session_history": [
                {
                    "workstream": "converter",
                    "session_id": "sess-aaa",
                    "first_seen_at": 1747000000000,
                    "last_seen_at": 1747000020000,
                }
            ],
        },
        "attachments": {
            "original_image": {
                "status": "attached",
                "filename": "original.png",
                "sha256": "a" * 64,
                "size_bytes": 123456,
            },
            "final_artifact": {
                "status": "attached",
                "filename": "final.3mf",
                "sha256": "b" * 64,
                "size_bytes": 234567,
                "artifact_type": "3mf",
            },
            "lut": {"status": "not_applicable"},
            "materials_bundle": {
                "status": "attached",
                "filename": "materials.zip",
                "compressed_size_bytes": 1000,
                "entry_count": 12,
                "included_dirs": ["BrandA", "BrandB"],
            },
            "screenshot": {
                "status": "attached",
                "filename": "screenshot.png",
                "size_bytes": 4096,
            },
        },
    }
    payload.update(overrides)
    return payload


def test_basic_payload_renders_all_sections(tmp_path: Path) -> None:
    payload = _sample_payload()
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)
    assert "# Bug Ticket LUM-20260511-001" in md
    assert "耗材档案8色10层高保真导出3MF是经典墙" in md
    assert "## Workflow Snapshot" in md
    assert "## Recent Actions (last 10)" in md
    assert "upload_image" in md
    assert "## Recent API Errors (last 5)" in md
    assert "/api/converter/generate" in md
    assert "## Attachments" in md
    assert "original.png" in md
    assert "final.3mf" in md
    assert "## Reproduction Suggestion" in md
    assert "## Session IDs for backend log grep" in md
    assert "sess-aaa" in md


def test_api_error_in_history_produces_suggestion(tmp_path: Path) -> None:
    payload = _sample_payload()
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)
    assert "/api/converter/generate" in md
    assert "500" in md


def test_material_mode_produces_suggestion(tmp_path: Path) -> None:
    payload = _sample_payload()
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)
    assert "10 层" in md or "(10 层)" in md or "10 layers" in md


def test_summary_text_is_concise() -> None:
    payload = _sample_payload()
    summary = generate_summary_text("LUM-20260511-001", payload)
    assert len(summary) < 2000, f"summary too long: {len(summary)} chars"
    assert "LUM-20260511-001" in summary
    assert "经典墙" in summary


def test_malformed_payload_no_exception(tmp_path: Path) -> None:
    generate_index_markdown("LUM-none", tmp_path, {})
    generate_summary_text("LUM-none", {})
    generate_index_markdown(
        "LUM-x",
        tmp_path,
        {"context": {"action_history": "not-a-list"}},
    )


def test_index_markdown_preserves_chinese(tmp_path: Path) -> None:
    payload = _sample_payload()
    payload["description"] = "中文描述：切换到 8 色时 3D 预览异常"
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)
    assert "中文描述" in md
    assert "3D 预览异常" in md


def test_no_api_errors_skips_that_section(tmp_path: Path) -> None:
    payload = _sample_payload()
    # Strip api_error entries from action history.
    payload["context"]["action_history"] = [
        e for e in payload["context"]["action_history"]
        if e.get("action_type") != "api_error"
    ]
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)
    assert "## Recent API Errors" not in md
