"""Unit tests for SVG vector native corpus profiling helpers."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from scripts.profile_vector_native_mesh_corpus import (
    _build_corpus_report,
    _warm_native_module_import,
    discover_svg_files,
    parse_args,
    sample_summary_row,
    write_corpus_outputs,
)


def test_discover_svg_files_returns_sorted_svg_paths(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    keep_a = tmp_path / "a.svg"
    keep_b = tmp_path / "B.SVG"
    keep_c = nested / "c.svg"
    ignored = tmp_path / "image.png"
    keep_b.write_text("<svg/>", encoding="utf-8")
    ignored.write_text("png", encoding="utf-8")
    keep_c.write_text("<svg/>", encoding="utf-8")
    keep_a.write_text("<svg/>", encoding="utf-8")

    result = discover_svg_files(tmp_path)

    assert result == [keep_b, keep_a, keep_c]


def test_sample_summary_row_reports_speedup_and_quality_pass() -> None:
    row = sample_summary_row(
        {
            "svg_name": "sample.svg",
            "status": "ok",
            "analysis": {
                "shape_count": 12,
                "seconds": 1.25,
                "stage_timings": {
                    "parse_s": 0.25,
                    "occlusion_s": 0.5,
                    "color_match_s": 0.125,
                },
            },
            "variants": {
                "baseline": {
                    "median_seconds": 4.0,
                    "stage_timings": {"extrude_bottom_s": 3.0},
                },
                "native_enabled": {
                    "median_seconds": 2.0,
                    "stage_timings": {"extrude_bottom_s": 1.5},
                    "native_stats": {
                        "native_group_count": 9,
                        "native_input_paths": 42,
                        "native_path_cache_hits": 7,
                        "native_path_cache_misses": 3,
                        "native_meshes": 8,
                        "fallback_groups": 1,
                        "native_seconds": 0.4,
                        "fallback_seconds": 0.2,
                        "mesh_convert_seconds": 0.3,
                        "pack_seconds": 0.1,
                        "native_split_retries": 1,
                        "native_split_group_count": 3,
                        "native_split_meshes": 2,
                        "native_split_fallback_groups": 1,
                        "native_merged_fallback_groups": 1,
                        "native_merged_fallback_polygons": 5,
                        "native_merged_fallback_input_paths": 12,
                        "native_merged_fallback_input_holes": 2,
                        "native_merged_fallback_skipped_groups": 1,
                        "surface_validation_seconds": 0.05,
                        "native_surface_checked": 8,
                        "native_surface_rejects": 1,
                        "fallback_reason_empty_native_mesh": 1,
                    },
                },
            },
            "comparison": {
                "totals": {
                    "volume": {"delta": -0.01, "rel_delta": -0.0001},
                    "area": {"delta": 0.02, "rel_delta": 0.0002},
                }
            },
            "quality_gate": {"passed": True, "failures": []},
        }
    )

    assert row["status"] == "PASS"
    assert row["build_speedup"] == 2.0
    assert row["extrude_speedup"] == 2.0
    assert row["native_group_count"] == 9
    assert row["native_input_paths"] == 42
    assert row["native_path_cache_hits"] == 7
    assert row["native_path_cache_misses"] == 3
    assert row["native_meshes"] == 8
    assert row["fallback_groups"] == 1
    assert row["native_seconds"] == 0.4
    assert row["fallback_seconds"] == 0.2
    assert row["mesh_convert_seconds"] == 0.3
    assert row["pack_seconds"] == 0.1
    assert row["native_split_retries"] == 1
    assert row["native_split_group_count"] == 3
    assert row["native_split_meshes"] == 2
    assert row["native_split_fallback_groups"] == 1
    assert row["native_merged_fallback_groups"] == 1
    assert row["native_merged_fallback_polygons"] == 5
    assert row["native_merged_fallback_input_paths"] == 12
    assert row["native_merged_fallback_input_holes"] == 2
    assert row["native_merged_fallback_skipped_groups"] == 1
    assert row["surface_validation_seconds"] == 0.05
    assert row["native_surface_checked"] == 8
    assert row["native_surface_rejects"] == 1
    assert row["fallback_reason_empty_native_mesh"] == 1
    assert row["fallback_reasons"] == "empty_native_mesh=1"
    assert row["volume_rel_delta"] == -0.0001
    assert row["area_rel_delta"] == 0.0002
    assert row["parse_seconds"] == 0.25
    assert row["occlusion_seconds"] == 0.5
    assert row["color_match_seconds"] == 0.125
    assert row["analyze_unaccounted_seconds"] == 0.375


def test_sample_summary_row_reports_errors() -> None:
    row = sample_summary_row(
        {
            "svg_name": "broken.svg",
            "status": "error",
            "error_type": "ValueError",
            "error_message": "invalid svg",
        }
    )

    assert row["status"] == "ERROR"
    assert row["error"] == "ValueError: invalid svg"
    assert row["build_speedup"] == 0.0
    assert row["native_seconds"] == 0.0
    assert row["fallback_reasons"] == ""


def test_parse_args_accepts_surface_validation_flag() -> None:
    args = parse_args(["/tmp/svg-corpus", "--validate-native-surface"])

    assert args.validate_native_surface is True


def test_parse_args_accepts_native_import_warmup_flag() -> None:
    args = parse_args(["/tmp/svg-corpus", "--warm-native-import"])

    assert args.warm_native_import is True


def test_warm_native_module_import_reports_available_module(monkeypatch, tmp_path: Path) -> None:
    fake_module = types.SimpleNamespace(
        __file__="/tmp/clipper2_batch.so",
        native_mesh_capabilities=lambda: {"triangulation_area_guard": True},
    )
    monkeypatch.setitem(sys.modules, "clipper2_batch", fake_module)
    args = parse_args([str(tmp_path), "--warm-native-import"])

    result = _warm_native_module_import(args)

    assert result["enabled"] is True
    assert result["available"] is True
    assert result["seconds"] >= 0.0
    assert result["module_file"] == "/tmp/clipper2_batch.so"
    assert result["triangulation_area_guard"] is True
    assert result["error_type"] == ""


def test_warm_native_module_import_can_be_skipped(tmp_path: Path) -> None:
    args = parse_args([str(tmp_path)])

    result = _warm_native_module_import(args)

    assert result == {
        "enabled": False,
        "available": False,
        "seconds": 0.0,
        "module_file": "",
        "triangulation_area_guard": False,
        "capability_error_type": "",
        "error_type": "",
        "error_message": "",
    }


def test_build_corpus_report_aggregates_analyze_stage_totals(tmp_path: Path) -> None:
    args = parse_args([str(tmp_path), "--repeats", "1"])
    rows = [
        {
            "svg_name": "a.svg",
            "status": "PASS",
            "baseline_build_seconds": 4.0,
            "native_build_seconds": 2.0,
            "analyze_seconds": 1.5,
            "baseline_extrude_seconds": 3.0,
            "native_extrude_seconds": 1.0,
            "parse_seconds": 0.4,
            "occlusion_seconds": 0.7,
            "color_match_seconds": 0.2,
            "analyze_unaccounted_seconds": 0.2,
            "native_group_count": 5,
            "native_input_paths": 20,
            "native_path_cache_hits": 2,
            "native_path_cache_misses": 4,
            "native_meshes": 4,
            "fallback_groups": 1,
            "native_seconds": 0.5,
            "fallback_seconds": 0.25,
            "mesh_convert_seconds": 0.3,
            "pack_seconds": 0.1,
            "native_split_retries": 1,
            "native_split_group_count": 3,
            "native_split_meshes": 2,
            "native_split_fallback_groups": 1,
            "native_merged_fallback_groups": 1,
            "native_merged_fallback_polygons": 5,
            "native_merged_fallback_input_paths": 12,
            "native_merged_fallback_input_holes": 2,
            "native_merged_fallback_skipped_groups": 1,
            "surface_validation_seconds": 0.05,
            "native_surface_checked": 4,
            "native_surface_rejects": 0,
            "fallback_reason_empty_native_mesh": 1,
            "fallback_reason_surface_reject": 0,
        },
        {
            "svg_name": "b.svg",
            "status": "PASS",
            "baseline_build_seconds": 6.0,
            "native_build_seconds": 3.0,
            "analyze_seconds": 2.0,
            "baseline_extrude_seconds": 4.0,
            "native_extrude_seconds": 2.0,
            "parse_seconds": 0.6,
            "occlusion_seconds": 0.8,
            "color_match_seconds": 0.3,
            "analyze_unaccounted_seconds": 0.3,
            "native_group_count": 7,
            "native_input_paths": 30,
            "native_path_cache_hits": 3,
            "native_path_cache_misses": 6,
            "native_meshes": 5,
            "fallback_groups": 2,
            "native_seconds": 0.75,
            "fallback_seconds": 0.35,
            "mesh_convert_seconds": 0.4,
            "pack_seconds": 0.2,
            "native_split_retries": 2,
            "native_split_group_count": 5,
            "native_split_meshes": 4,
            "native_split_fallback_groups": 1,
            "native_merged_fallback_groups": 2,
            "native_merged_fallback_polygons": 7,
            "native_merged_fallback_input_paths": 14,
            "native_merged_fallback_input_holes": 3,
            "native_merged_fallback_skipped_groups": 2,
            "surface_validation_seconds": 0.15,
            "native_surface_checked": 5,
            "native_surface_rejects": 1,
            "fallback_reason_empty_native_mesh": 1,
            "fallback_reason_surface_reject": 1,
        },
    ]

    args.validate_native_surface = True
    native_warmup = {
        "enabled": True,
        "available": True,
        "seconds": 0.123,
        "module_file": "/tmp/clipper2_batch.so",
        "triangulation_area_guard": True,
        "capability_error_type": "",
        "error_type": "",
        "error_message": "",
    }
    report = _build_corpus_report(
        input_path=tmp_path,
        samples=[],
        rows=rows,
        args=args,
        native_warmup=native_warmup,
    )

    assert report["summary"]["analyze_stage_totals_seconds"] == {
        "parse": 1.0,
        "occlusion": 1.5,
        "color_match": 0.5,
        "unaccounted": 0.5,
    }
    assert report["summary"]["native_surface_validation"] is True
    assert report["summary"]["native_import_warmup"] == native_warmup
    assert report["summary"]["native_stat_totals"] == {
            "native_group_count": 12,
            "native_input_paths": 50,
            "native_path_cache_hits": 5,
            "native_path_cache_misses": 10,
            "native_meshes": 9,
            "native_coalesced_meshes": 0,
            "native_coalesced_slots": 0,
            "native_output_meshes": 0,
            "fallback_groups": 3,
        "native_seconds": 1.25,
            "fallback_seconds": 0.6,
            "mesh_convert_seconds": 0.7,
            "pack_seconds": 0.30000000000000004,
            "native_split_retries": 3,
            "native_split_group_count": 8,
            "native_split_meshes": 6,
            "native_split_fallback_groups": 2,
            "native_merged_fallback_groups": 3,
            "native_merged_fallback_polygons": 12,
            "native_merged_fallback_input_paths": 26,
            "native_merged_fallback_input_holes": 5,
            "native_merged_fallback_skipped_groups": 3,
            "surface_validation_seconds": 0.2,
            "native_surface_checked": 9,
            "native_surface_rejects": 1,
        "fallback_reason_empty_native_mesh": 2,
        "fallback_reason_surface_reject": 1,
    }


def test_write_corpus_outputs_keeps_late_fallback_reason_columns(tmp_path: Path) -> None:
    args = parse_args([str(tmp_path), "--repeats", "1"])
    base_row = {
        "status": "PASS",
        "error": "",
        "shape_count": 1,
        "analyze_seconds": 1.0,
        "parse_seconds": 0.4,
        "occlusion_seconds": 0.5,
        "color_match_seconds": 0.1,
        "analyze_unaccounted_seconds": 0.0,
        "baseline_build_seconds": 2.0,
        "native_build_seconds": 1.0,
        "build_speedup": 2.0,
        "baseline_extrude_seconds": 1.5,
        "native_extrude_seconds": 0.75,
        "extrude_speedup": 2.0,
        "native_meshes": 1,
        "fallback_groups": 0,
        "volume_rel_delta": 0.0,
        "area_rel_delta": 0.0,
        "quality_failures": "",
    }
    first_row = {**base_row, "svg_name": "a.svg", "fallback_reason_empty_native_mesh": 1}
    second_row = {**base_row, "svg_name": "b.svg", "fallback_reason_surface_reject": 1}
    rows = [first_row, second_row]
    report = _build_corpus_report(input_path=tmp_path, samples=[], rows=rows, args=args)

    outputs = write_corpus_outputs(report, tmp_path / "out")

    csv_text = Path(outputs["csv"]).read_text(encoding="utf-8")
    header = csv_text.splitlines()[0]
    assert "fallback_reason_empty_native_mesh" in header
    assert "fallback_reason_surface_reject" in header
