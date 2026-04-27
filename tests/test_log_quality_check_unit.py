"""Unit tests for the log quality check helper functions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.log_quality_check as log_quality_check
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


def _assert_replace_family_step_is_first_class(step: str) -> None:
    workflow = _parse_workflow(
        f"startup,lut_list,lut_colors,preview,generate,{step}"
    )

    assert workflow == ["startup", "lut_list", "lut_colors", "preview", "generate", step]
    assert step in WORKFLOW_ORDER
    assert step in WORKFLOW_STEPS


def test_replace_bw_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_bw")


def test_replace_8color_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_8color")


def test_replace_5color_ext_workflow_step_is_first_class() -> None:
    _assert_replace_family_step_is_first_class("replace_5color_ext")


def test_extract_workflow_step_is_first_class() -> None:
    """The extractor workflow must be accepted by the quality gate."""

    workflow = _parse_workflow(
        "startup,lut_list,lut_colors,preview,generate,replace,extract"
    )

    assert workflow == [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    assert "extract" in WORKFLOW_ORDER
    assert "extract" in WORKFLOW_STEPS


def test_parse_workflow_rejects_vector_and_replace_together() -> None:
    try:
        _parse_workflow("startup,lut_list,lut_colors,preview,generate,vector,replace")
    except Exception as exc:
        assert "should not be combined" in str(exc)
    else:
        raise AssertionError("Expected vector + replace workflow to be rejected")


def test_parse_workflow_rejects_replace_family_combinations() -> None:
    workflow_prefix = "startup,lut_list,lut_colors,preview,generate"
    conflicts = [
        ("replace", "replace_bw"),
        ("replace", "replace_8color"),
        ("replace", "replace_5color_ext"),
        ("replace_bw", "replace_8color"),
        ("replace_bw", "replace_5color_ext"),
        ("replace_8color", "replace_5color_ext"),
    ]

    for first, second in conflicts:
        with pytest.raises(Exception) as exc_info:
            _parse_workflow(f"{workflow_prefix},{first},{second}")

        message = str(exc_info.value)
        assert first in message
        assert second in message
        assert "replace family" in message
        assert "Pick exactly one" in message

    with pytest.raises(Exception) as exc_info:
        _parse_workflow(f"{workflow_prefix},vector,replace_bw")

    message = str(exc_info.value)
    assert "vector" in message
    assert "replace_bw" in message
    assert "replace family" in message
    assert "run 'vector' separately" in message or "Pick exactly one" in message


def test_main_returns_script_error_for_replace_family_combination(capsys) -> None:
    exit_code = log_quality_check.main(
        ["--mode", "fast", "--workflow", "startup,lut_list,lut_colors,preview,generate,replace,replace_bw"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "replace family" in captured.err
    assert "Pick exactly one" in captured.err


def test_replace_family_member_dispatches_correct_color_mode(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_execute_replace_workflow(client, **kwargs):
        captured.append({"client": client, **kwargs})

    monkeypatch.setattr(
        log_quality_check, "_execute_replace_workflow", fake_execute_replace_workflow
    )

    client = object()
    wrappers = {
        "replace_bw": log_quality_check._execute_replace_bw_workflow,
        "replace_8color": log_quality_check._execute_replace_8color_workflow,
        "replace_5color_ext": log_quality_check._execute_replace_5color_ext_workflow,
    }
    for step, execute_workflow in wrappers.items():
        color_mode, lut_name = log_quality_check.ALTERNATE_REPLACE_CONFIG[step]
        captured.clear()

        execute_workflow(client)

        assert captured == [
            {
                "client": client,
                "mode": step,
                "color_mode": color_mode,
                "lut_name": lut_name,
            }
        ]


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


def test_replace_bw_fast_and_full_canary_requirements_differ() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace_bw",
    ]

    fast_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={"converter_region_replace_timing": 1},
    )
    full_checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={"converter_region_replace_timing": 1},
    )

    fast_by_name = {check.name: check for check in fast_checks}
    full_by_name = {check.name: check for check in full_checks}

    assert set(fast_by_name) == {"workflow_event_converter_region_replace_timing"}
    assert fast_by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert full_by_name["workflow_event_converter_region_replace_timing"].passed is True
    assert (
        full_by_name["workflow_event_vector_matched_rgb_overrides_applied"].passed
        is False
    )


def test_full_extract_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "vector_matched_rgb_overrides_applied": 1,
            "extractor_extract_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="full",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_extract_done"].passed is True
    assert missing_by_name["workflow_event_extractor_extract_done"].passed is False


def test_fast_extract_workflow_requires_canary_event() -> None:
    workflow = [
        "startup",
        "lut_list",
        "lut_colors",
        "preview",
        "generate",
        "replace",
        "extract",
    ]
    checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={
            "converter_region_replace_timing": 1,
            "extractor_extract_done": 1,
        },
    )
    missing_checks = _workflow_required_event_checks(
        mode="fast",
        workflow=workflow,
        event_counts={},
    )

    by_name = {check.name: check for check in checks}
    missing_by_name = {check.name: check for check in missing_checks}

    assert by_name["workflow_event_extractor_extract_done"].passed is True
    assert missing_by_name["workflow_event_extractor_extract_done"].passed is False


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
