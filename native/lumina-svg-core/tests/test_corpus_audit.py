"""Anonymous corpus completeness and performance report contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "corpus_audit.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("corpus_audit", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_audit_records_parser_completeness_without_source_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "first.svg").write_text(
        "<svg viewBox='0 0 10 10'>"
        "<path fill='#123456' fill-rule='evenodd' d='"
        "M0 0H10V10H0Z M3 3H7V7H3Z M1 1L2 2L3 3Z'/>"
        "</svg>",
        encoding="utf-8",
    )
    (tmp_path / "second.svg").write_text(
        "<svg viewBox='0 0 10 10'>"
        "<rect width='7' height='10' fill='red' fill-opacity='.5'/>"
        "<rect x='3' width='7' height='10' fill='blue' fill-opacity='.5'/>"
        "</svg>",
        encoding="utf-8",
    )

    report = _load_tool().audit_corpus(
        tmp_path,
        target_width_mm=10.0,
        tolerance_mm=0.02,
    )

    assert report["schema_version"] == 3
    assert report["summary"]["file_count"] == 2
    assert report["summary"]["supported_count"] == 2
    assert report["summary"]["input_paint_count"] == 3
    assert report["summary"]["raw_output_paint_count"] == 3
    assert report["summary"]["partial_alpha_raw_paint_count"] == 2
    assert report["summary"]["partial_alpha_visible_paint_count"] == 3
    assert report["summary"]["composite_visible_paint_count"] == 1
    assert report["summary"]["visible_contributor_count"] == 5
    assert report["summary"]["unprintable_fragment_count"] == 1
    assert report["summary"]["unprintable_reasons"] == {"line_only": 1}
    assert report["summary"]["visible_partition_area_delta_max"] < 1e-8
    assert (
        report["summary"]["visible_partition_area_relative_delta_max"]
        < 1e-12
    )
    assert report["performance"]["total_seconds"] > 0
    assert report["performance"]["p95_seconds"] > 0
    assert report["performance"]["corpus_process_peak_rss_bytes"] >= 0
    assert "peak_rss_bytes" not in report["performance"]

    assert [item["anonymous_id"] for item in report["documents"]] == [
        "svg-000001",
        "svg-000002",
    ]
    first = report["documents"][0]
    assert first["input_paint_count"] == 1
    assert first["raw_output_paint_count"] == 1
    assert first["visible_output_paint_count"] == 1
    assert first["partial_alpha_raw_paint_count"] == 0
    assert first["partial_alpha_visible_paint_count"] == 0
    assert first["composite_visible_paint_count"] == 0
    assert first["visible_contributor_count"] == 1
    assert first["visible_hole_count"] == 1
    assert first["unprintable_fragment_count"] == 1
    assert first["unprintable_reasons"] == {"line_only": 1}
    assert first["visible_partition_area_delta"] == pytest.approx(0.0)
    assert first["visible_partition_area_relative_delta"] == pytest.approx(
        0.0
    )
    assert "path" not in first
    assert "sha256" not in first
    assert "byte_size" not in first
    assert "source_hashes_recorded" not in report

    second = report["documents"][1]
    assert second["partial_alpha_raw_paint_count"] == 2
    assert second["partial_alpha_visible_paint_count"] == 3
    assert second["composite_visible_paint_count"] == 1
    assert second["visible_contributor_count"] == 4


def test_corpus_audit_cli_includes_strokes_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "stroke.svg").write_text(
        "<svg viewBox='0 0 10 10'>"
        "<path d='M1 5H9' fill='none' stroke='blue' stroke-width='1'/>"
        "</svg>",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    module = _load_tool()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(TOOL_PATH),
            "--corpus",
            str(corpus),
            "--output",
            str(output),
        ],
    )

    assert module.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["settings"]["allow_strokes"] is True
    assert report["summary"]["input_paint_count"] == 1
    assert report["summary"]["raw_output_paint_count"] == 1


def test_corpus_audit_progress_is_anonymous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = tmp_path / "private-corpus"
    corpus.mkdir()
    private_name = "customer-secret-name.svg"
    (corpus / private_name).write_text(
        "<svg viewBox='0 0 1 1'><rect width='1' height='1'/></svg>",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    module = _load_tool()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(TOOL_PATH),
            "--corpus",
            str(corpus),
            "--output",
            str(output),
            "--progress",
        ],
    )

    assert module.main() == 0
    captured = capsys.readouterr()
    assert "svg-000001" in captured.err
    assert "supported" in captured.err
    assert private_name not in captured.err
