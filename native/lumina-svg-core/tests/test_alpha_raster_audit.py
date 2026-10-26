"""Transparent-canvas raster differential audit contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

import lumina_svg_core


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOOL_PATH = PACKAGE_ROOT / "tools" / "alpha_raster_audit.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "alpha_raster_audit", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_raster_comparison_keeps_interior_mismatches_visible() -> None:
    module = _load_tool()
    reference = np.zeros((21, 21, 4), dtype=np.uint8)
    candidate = reference.copy()
    reference[2:19, 2:19] = (255, 0, 0, 128)
    candidate[2:19, 2:19] = (254, 0, 0, 128)

    within_one = module._comparison(reference, candidate, 1)
    assert within_one["maximum_interior_channel_error_u8"] == 1
    assert within_one["interior_coverage_disagreement_pixel_count"] == 0

    missing = candidate.copy()
    missing[5:16, 5:16] = (0, 0, 0, 0)
    missing_interior = module._comparison(reference, missing, 1)
    assert missing_interior["maximum_interior_channel_error_u8"] > 1
    assert missing_interior[
        "interior_coverage_disagreement_pixel_count"
    ] > 0
    assert missing_interior["maximum_channel_error_u8"] == 255


def test_visible_svg_export_preserves_alpha_regions_without_source_identity(
    tmp_path: Path,
) -> None:
    module = _load_tool()
    result = lumina_svg_core.analyze_svg(
        FIXTURES / "alpha_source_over.svg", 12.0, 0.02
    )
    destination = tmp_path / "visible.svg"

    module._write_visible_svg(result, destination)

    exported = destination.read_text(encoding="utf-8")
    assert exported.count("<path ") == 3
    assert 'fill="rgba(255,0,0,0.5)"' in exported
    assert 'fill="rgba(85,0,170,0.75)"' in exported
    assert 'fill="rgba(0,0,255,0.5)"' in exported
    assert "alpha_source_over.svg" not in exported


def test_previous_report_selects_only_anonymous_partial_alpha_ids(
    tmp_path: Path,
) -> None:
    module = _load_tool()
    report_path = tmp_path / "previous.json"
    report_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "anonymous_id": "svg-000001",
                        "reason_code": "unsupported_partial_alpha",
                    },
                    {
                        "anonymous_id": "svg-000002",
                        "reason_code": "unsupported_gradient",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert module._selected_ids(report_path) == {"svg-000001"}


def test_raster_audit_gate_requires_every_selected_document_to_match() -> None:
    module = _load_tool()
    passing = {
        "summary": {
            "selected_document_count": 2,
            "measured_document_count": 2,
            "matched_document_count": 2,
            "mismatch_document_count": 0,
            "unsupported_document_count": 0,
            "missing_document_count": 0,
        }
    }

    assert module._report_passed(passing)
    for field in (
        "mismatch_document_count",
        "unsupported_document_count",
        "missing_document_count",
    ):
        failing = {"summary": dict(passing["summary"])}
        failing["summary"][field] = 1
        assert not module._report_passed(failing)

    incomplete = {"summary": dict(passing["summary"])}
    incomplete["summary"]["measured_document_count"] = 1
    incomplete["summary"]["matched_document_count"] = 1
    assert not module._report_passed(incomplete)
