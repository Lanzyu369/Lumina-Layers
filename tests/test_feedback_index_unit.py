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
                        "request_id": "req-ticket-500",
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
    assert "req-ticket-500" in md
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


# ---------------------------------------------------------------------------
# Advanced Generation Parameters rendering (task 7.3)
# ---------------------------------------------------------------------------

import logging

import api.feedback_index as feedback_index


def _full_advanced_params() -> dict[str, object]:
    """Return a fully populated ``advanced_params`` dict used in renders.

    构造高级参数测试夹具：8 个开关全部明确设置（True/False 混合）。
    """
    return {
        "dimensions": {
            "target_width_mm": 120.0,
            "target_height_mm": 80.0,
            "spacer_thick": 0.2,
            "base_spacer_thick": 0.2,
        },
        "generation": {
            "structure_mode": "flat",
            "modeling_mode": "high_fidelity",
        },
        "relief": {"enable_relief": True},
        "outline": {"enable_outline": True},
        "cloisonne": {"enable_cloisonne": False},
        "coating": {"enable_coating": False},
        "loop": {"add_loop": True},
        "fridge_magnet": {"enable_fridge_magnet": True},
        "puzzle": {"puzzleEnabled": False},
        "large_format": {"largeFormatEnabled": True},
    }


def _payload_with_advanced(advanced: object, **overrides) -> dict[str, object]:
    """Build a payload that carries ``advanced_params`` in its context.

    生成带有 ``advanced_params`` 的 payload，方便测试专注渲染路径。
    """
    payload = _sample_payload(**overrides)
    payload["context"]["advanced_params"] = advanced
    return payload


def test_index_renders_advanced_params_section_with_eight_toggles(tmp_path: Path) -> None:
    """Full advanced params → one section with 8 toggle lines and dimensions."""
    payload = _payload_with_advanced(_full_advanced_params())
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)

    assert "## Advanced Generation Parameters" in md
    # Dimensions line with × separator and mm unit.
    assert "Dimensions: 120.0 × 80.0 mm" in md
    # All eight toggle state lines must be present.
    assert "- enable_relief: enabled" in md
    assert "- enable_outline: enabled" in md
    assert "- enable_cloisonne: disabled" in md
    assert "- enable_coating: disabled" in md
    assert "- add_loop: enabled" in md
    assert "- enable_fridge_magnet: enabled" in md
    assert "- puzzleEnabled: disabled" in md
    assert "- largeFormatEnabled: enabled" in md

    # Section ordering: Workflow Snapshot → Advanced Generation Parameters → Recent Actions.
    idx_snapshot = md.index("## Workflow Snapshot")
    idx_advanced = md.index("## Advanced Generation Parameters")
    idx_actions = md.index("## Recent Actions")
    assert idx_snapshot < idx_advanced < idx_actions


def test_index_advanced_params_absent_renders_fallback(tmp_path: Path) -> None:
    """Missing or None ``advanced_params`` → ``_(not captured)_`` placeholder."""
    payload_none = _payload_with_advanced(None)
    md_none = generate_index_markdown("LUM-20260511-001", tmp_path, payload_none)
    assert "## Advanced Generation Parameters" in md_none
    assert "_(not captured)_" in md_none
    # No toggle lines should leak through the fallback.
    assert "enable_relief" not in md_none

    # Key absent entirely (not just None) — same fallback behavior.
    payload_absent = _sample_payload()
    payload_absent["context"].pop("advanced_params", None)
    md_absent = generate_index_markdown("LUM-20260511-001", tmp_path, payload_absent)
    assert "_(not captured)_" in md_absent


def test_index_advanced_params_partial_substitutes_missing(tmp_path: Path) -> None:
    """Partial dimensions render ``(missing)`` for the absent field.

    缺失的字段用 ``(missing)`` 占位，其他字段仍然正常渲染。
    """
    advanced = _full_advanced_params()
    # Drop target_width_mm but keep target_height_mm and the rest.
    advanced["dimensions"].pop("target_width_mm")  # type: ignore[union-attr]
    payload = _payload_with_advanced(advanced)
    md = generate_index_markdown("LUM-20260511-001", tmp_path, payload)

    assert "Dimensions: (missing) × 80.0 mm" in md
    # Remaining toggle lines still rendered.
    assert "- enable_relief: enabled" in md
    assert "- largeFormatEnabled: enabled" in md


def test_index_advanced_params_section_failure_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the formatter raises, fall back to the placeholder and log WARNING.

    渲染抛异常时：index 正常落到兜底文本，日志记录 WARNING 事件。
    """
    def _boom(_context: dict) -> str:
        raise RuntimeError("boom-advanced")

    monkeypatch.setattr(feedback_index, "_format_advanced_params_section", _boom)

    # The lumina logger family has propagate=False, so attach the caplog
    # handler directly to the target logger.
    target_logger = logging.getLogger("lumina.api.feedback_index")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="lumina.api.feedback_index")

    try:
        md = generate_index_markdown(
            "LUM-20260511-001",
            tmp_path,
            _payload_with_advanced(_full_advanced_params()),
        )
    finally:
        target_logger.removeHandler(caplog.handler)

    # Fallback text rendered in place of the section.
    assert "_(not captured)_" in md
    # Rest of the markdown remains intact.
    assert "# Bug Ticket LUM-20260511-001" in md
    assert "## Workflow Snapshot" in md
    assert "## Recent Actions" in md

    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING
        and getattr(rec, "event", None) == "feedback_advanced_params_failed"
    ]
    assert warnings, "expected a feedback_advanced_params_failed WARNING record"
    warning = warnings[0]
    assert getattr(warning, "error_type") == "RuntimeError"
    assert getattr(warning, "error_message") == "boom-advanced"
    assert getattr(warning, "surface") == "index_markdown"


def test_summary_renders_active_toggles_line() -> None:
    """Active toggles produce the Chinese summary line with the six labels.

    摘要行使用 6 个面向用户的标签：浮雕 / 描边 / 景泰蓝 / 冰箱贴 / 拼图 / 大幅面。
    """
    advanced = _full_advanced_params()
    # Activate every summary-visible toggle so all six labels show up.
    advanced["cloisonne"] = {"enable_cloisonne": True}
    advanced["puzzle"] = {"puzzleEnabled": True}
    payload = _payload_with_advanced(advanced)

    summary = generate_summary_text("LUM-20260511-001", payload)
    expected_line = "尺寸 120.0×80.0 mm，已开启：浮雕、描边、景泰蓝、冰箱贴、拼图、大幅面。"
    assert expected_line in summary

    # Line placement: after the workflow line, before 最近操作：.
    idx_workflow = summary.index("提交时工作流")
    idx_advanced = summary.index(expected_line)
    idx_actions = summary.index("最近操作：")
    assert idx_workflow < idx_advanced < idx_actions


def test_summary_advanced_params_none_uses_fallback() -> None:
    """``advanced_params=None`` → ``高级参数：(未采集)`` summary line."""
    payload = _payload_with_advanced(None)
    summary = generate_summary_text("LUM-20260511-001", payload)
    assert "高级参数：(未采集)" in summary
    # Fallback sits between the workflow line and the 最近操作 line.
    idx_workflow = summary.index("提交时工作流")
    idx_fallback = summary.index("高级参数：(未采集)")
    idx_actions = summary.index("最近操作：")
    assert idx_workflow < idx_fallback < idx_actions


def test_summary_advanced_params_size_trimmed_uses_fallback() -> None:
    """``_size_trimmed=True`` marker → summary falls back to ``(未采集)``.

    前端侧已压缩过的 payload 不参与具体渲染，走兜底摘要。
    """
    advanced = _full_advanced_params()
    advanced["_size_trimmed"] = True
    payload = _payload_with_advanced(advanced)
    summary = generate_summary_text("LUM-20260511-001", payload)
    assert "高级参数：(未采集)" in summary
    # The populated "尺寸 ..." line must NOT leak through.
    assert "尺寸 " not in summary or "尺寸 120.0×80.0 mm" not in summary
