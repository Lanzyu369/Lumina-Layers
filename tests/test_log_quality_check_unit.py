"""Unit tests for the log quality check helper functions."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_logs import event_from_line, parse_json_object
from scripts.log_quality_check import (
    CheckResult,
    WORKFLOW_ORDER,
    WORKFLOW_STEPS,
    _parse_workflow,
    _scan_log_file_for_governance_metrics,
    _select_replace_click,
    _workflow_required_event_checks,
)


def _write_json_lines(path: Path, payloads: list[dict[str, object]]) -> None:
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_scan_empty_file_returns_zero_metrics(tmp_path: Path) -> None:
    log_path = tmp_path / "empty.log"
    log_path.write_text("", encoding="utf-8")

    metrics = _scan_log_file_for_governance_metrics(log_path)

    assert metrics["info_lines"] == 0
    assert metrics["warning_lines"] == 0
    assert metrics["error_lines"] == 0
    assert metrics["catch_all_event_count"] == 0
    assert metrics["ansi_field_count"] == 0
    assert metrics["bracket_tag_message_count"] == 0
    assert metrics["log_file_configured_count"] == 0


def test_scan_counts_catch_all_request_log_event(tmp_path: Path) -> None:
    log_path = tmp_path / "catch-all.log"
    _write_json_lines(
        log_path,
        [{"level": "INFO", "event": "request_log", "message": "legacy bucket"}],
    )

    metrics = _scan_log_file_for_governance_metrics(log_path)

    assert metrics["info_lines"] == 1
    assert metrics["catch_all_event_count"] == 1


def test_scan_counts_bracket_tag_message_prefix(tmp_path: Path) -> None:
    log_path = tmp_path / "bracket.log"
    _write_json_lines(
        log_path,
        [
            {
                "level": "INFO",
                "event": "isolated_pixels_cleaned",
                "message": "[ISOLATED_CLEANUP] removed pixels",
            }
        ],
    )

    metrics = _scan_log_file_for_governance_metrics(log_path)

    assert metrics["bracket_tag_message_count"] == 1


def test_scan_counts_json_escaped_ansi_sequences(tmp_path: Path) -> None:
    log_path = tmp_path / "ansi.log"
    _write_json_lines(
        log_path,
        [
            {
                "level": "INFO",
                "event": "uvicorn",
                "message": "\u001b[36mGET /api/health\u001b[0m",
            }
        ],
    )

    metrics = _scan_log_file_for_governance_metrics(log_path)

    assert metrics["ansi_field_count"] == 1


def test_scan_allows_client_log_event(tmp_path: Path) -> None:
    log_path = tmp_path / "client.log"
    _write_json_lines(
        log_path,
        [{"level": "INFO", "event": "client_log", "message": "frontend timing"}],
    )

    metrics = _scan_log_file_for_governance_metrics(log_path)

    assert metrics["catch_all_event_count"] == 0


def test_vector_workflow_step_is_first_class() -> None:
    """The SVG-native vector workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("startup,lut_list,lut_colors,preview,generate,vector")

    assert workflow == ["startup", "lut_list", "lut_colors", "preview", "generate", "vector"]
    assert "vector" in WORKFLOW_ORDER
    assert "vector" in WORKFLOW_STEPS


def test_replace_workflow_step_is_first_class() -> None:
    """The replace workflow must be accepted by the quality gate."""

    workflow = _parse_workflow("startup,lut_list,lut_colors,preview,generate,replace")

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
    ]
    assert "replace" in WORKFLOW_ORDER
    assert "replace" in WORKFLOW_STEPS


def test_parse_workflow_rejects_vector_and_replace_together() -> None:
    try:
        _parse_workflow("startup,lut_list,lut_colors,preview,generate,vector,replace")
    except Exception as exc:
        assert "should not be combined" in str(exc)
    else:
        raise AssertionError("Expected vector + replace workflow to be rejected")


def test_full_replace_workflow_requires_canary_events() -> None:
    checks = _workflow_required_event_checks(
        mode="full",
        workflow=["startup", "lut_list", "lut_colors", "preview", "generate", "replace"],
        event_counts={"converter_region_replace_timing": 1},
    )

    by_name = {check.name: check for check in checks}

    assert by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert (
        by_name["workflow_event_vector_matched_rgb_overrides_applied"].passed
        is False
    )


def test_fast_replace_workflow_does_not_require_worker_canary_event() -> None:
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=["startup", "lut_list", "lut_colors", "preview", "generate", "replace"],
        event_counts={"converter_region_replace_timing": 1},
    )

    assert {check.name for check in checks} == {
        "workflow_event_converter_region_replace_timing"
    }
    assert all(check.passed for check in checks)


def test_replace_click_targets_filled_band_for_ring_fixture() -> None:
    payload = {"dimensions": {"width": 600, "height": 600}}

    assert _select_replace_click(payload) == (200, 300)


def test_check_result_evaluate_marks_passing_threshold() -> None:
    result = CheckResult.evaluate(
        name="info_lines_within_budget",
        actual=18,
        operator="<=",
        threshold=30,
    )

    assert result.passed is True
    assert result.actual == 18
    assert result.threshold == 30


def test_check_result_evaluate_marks_failing_threshold() -> None:
    result = CheckResult.evaluate(
        name="no_unstructured_lines",
        actual=1,
        operator="==",
        threshold=0,
    )

    assert result.passed is False


def test_parse_json_object_accepts_prefixed_json() -> None:
    payload = parse_json_object('INFO {"event":"worker_pool_started","level":"INFO"}')

    assert payload == {"event": "worker_pool_started", "level": "INFO"}


def test_event_from_line_reports_unstructured_lines() -> None:
    event, structured = event_from_line("not-json")

    assert event == "unstructured"
    assert structured is False
