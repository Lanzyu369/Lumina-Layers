"""Unit tests for SVG vector analyze hotspot profiling helpers."""

from __future__ import annotations

from pathlib import Path
import hashlib

from scripts.profile_vector_analyze_hotspots import (
    _build_report,
    _profile_rows_from_raw_stats,
    _render_markdown,
    _write_synthetic_compound_fixture,
)


def test_write_synthetic_compound_fixture_is_reproducible(tmp_path: Path) -> None:
    fixture_path = tmp_path / "compound-49-to-35587.svg"

    metadata = _write_synthetic_compound_fixture(fixture_path)
    payload = fixture_path.read_bytes()

    assert metadata == {
        "grid_size": 189,
        "total_cells": 35587,
        "path_groups": 49,
        "viewbox_size": 160.0,
        "sha256": "c4f7d322ca179553aeed5abf71aaa51eadbe1865bcfff060c30effc08a05f8cb",
    }
    assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
    assert payload.count(b"<path ") == 49
    assert payload.count(b"M") == 35587


def test_profile_rows_from_raw_stats_selects_vector_hotspots() -> None:
    raw_stats = {
        ("/tmp/vector_engine.py", 3219, "_clip_occlusion"): (1, 1, 0.5, 2.5, {}),
        ("/venv/shapely/set_operations.py", 463, "union_all"): (20, 20, 1.7, 1.8, {}),
        ("/tmp/other.py", 10, "unrelated"): (5, 5, 9.0, 9.0, {}),
    }

    summary = _profile_rows_from_raw_stats(raw_stats, limit=5)

    assert summary["top"][0]["function"] == "other.py:10:unrelated"
    selected_functions = [row["function"] for row in summary["selected"]]
    assert "vector_engine.py:3219:_clip_occlusion" in selected_functions
    assert "set_operations.py:463:union_all" in selected_functions
    assert all("unrelated" not in item for item in selected_functions)


def test_build_report_aggregates_stage_totals_and_hotspot_rows(tmp_path: Path) -> None:
    samples = [
        {
            "status": "ok",
            "svg_name": "a.svg",
            "svg_path": str(tmp_path / "a.svg"),
            "analysis_seconds": 3.0,
            "shape_count": 10,
            "stage_timings": {"parse_s": 1.0, "occlusion_s": 1.5, "color_match_s": 0.25},
            "profile": {
                "selected": [
                    {
                        "function": "vector_engine.py:3219:_clip_occlusion",
                        "calls": 1,
                        "primitive_calls": 1,
                        "tottime_s": 0.2,
                        "cumtime_s": 1.5,
                    }
                ]
            },
        },
        {
            "status": "ok",
            "svg_name": "b.svg",
            "svg_path": str(tmp_path / "b.svg"),
            "analysis_seconds": 2.0,
            "shape_count": 5,
            "stage_timings": {"parse_s": 0.5, "occlusion_s": 0.75, "color_match_s": 0.1},
            "profile": {"selected": []},
        },
    ]

    report = _build_report(input_path=tmp_path, samples=samples)

    assert report["summary"]["sample_count"] == 2
    assert report["summary"]["ok_count"] == 2
    assert report["summary"]["analysis_total_seconds"] == 5.0
    assert report["summary"]["stage_totals_seconds"] == {
        "parse": 1.5,
        "occlusion": 2.25,
        "color_match": 0.35,
        "unaccounted": 0.9,
    }
    assert report["slowest"]["analysis"][0]["svg_name"] == "a.svg"
    assert report["slowest"]["occlusion"][0]["svg_name"] == "a.svg"


def test_render_markdown_includes_selected_profile_rows(tmp_path: Path) -> None:
    report = _build_report(
        input_path=tmp_path,
        samples=[
            {
                "status": "ok",
                "svg_name": "a.svg",
                "svg_path": str(tmp_path / "a.svg"),
                "analysis_seconds": 3.0,
                "shape_count": 10,
                "stage_timings": {"parse_s": 1.0, "occlusion_s": 1.5, "color_match_s": 0.25},
                "profile": {
                    "selected": [
                        {
                            "function": "vector_engine.py:3219:_clip_occlusion",
                            "calls": 1,
                            "primitive_calls": 1,
                            "tottime_s": 0.2,
                            "cumtime_s": 1.5,
                        }
                    ]
                },
            }
        ],
    )

    markdown = _render_markdown(report)

    assert "Analyze Hotspots" in markdown
    assert "parse=1.000s" in markdown
    assert "vector_engine.py:3219:_clip_occlusion" in markdown
