"""Unit coverage for the reproducible dynamic-material benchmark CLI."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from core import material_dynamic_solver as dynamic_solver
from scripts import profile_dynamic_material_layers as profile


def test_target_counts_parser_is_explicit_and_deterministic() -> None:
    assert profile._parse_target_counts("48, 256,8192") == (48, 256, 8192)

    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        profile._parse_target_counts("48,0")
    with pytest.raises(argparse.ArgumentTypeError, match="duplicates"):
        profile._parse_target_counts("48,48")


def test_material_file_summary_hashes_utf8_paths_and_contents(tmp_path: Path) -> None:
    material_dir = tmp_path / "品牌" / "红色"
    material_dir.mkdir(parents=True)
    archive = material_dir / "material.json"
    archive.write_text('{"material_name":"红色"}', encoding="utf-8")

    first, first_digest = profile._material_file_summaries(
        tmp_path, ["品牌/红色"]
    )
    archive.write_text('{"material_name":"深红色"}', encoding="utf-8")
    second, second_digest = profile._material_file_summaries(
        tmp_path, ["品牌/红色"]
    )

    assert first[0]["files"][0]["path"] == "material.json"
    assert first[0]["files"][0]["bytes"] != second[0]["files"][0]["bytes"]
    assert first_digest != second_digest


def test_backend_comparison_marks_unavailable_numba(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = dynamic_solver.build_dynamic_candidate_catalog(
        score_srgb=np.asarray([[0, 0, 0], [255, 255, 255]], dtype=np.uint8),
        print_recipes_bottom_to_top=np.asarray(
            [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32
        ),
        actual_layer_counts=np.asarray([5, 5], dtype=np.int16),
        max_layer_count=5,
    )
    monkeypatch.setattr(dynamic_solver, "_NUMBA_AVAILABLE", False)

    comparison = profile._compare_search_backends(
        np.asarray([[10, 20, 30]], dtype=np.uint8),
        catalog,
        5,
        5,
    )

    assert comparison["status"] == "numba_unavailable"
    assert comparison["numpy"]["indices_sha256"]
    assert comparison["numba"] is None
    assert comparison["exact_identity"] is None


def test_backend_comparison_reports_selection_identity_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The profile must distinguish selected recipes from float bit patterns."""

    catalog = dynamic_solver.build_dynamic_candidate_catalog(
        score_srgb=np.asarray([[0, 0, 0], [255, 255, 255]], dtype=np.uint8),
        print_recipes_bottom_to_top=np.asarray(
            [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32
        ),
        actual_layer_counts=np.asarray([5, 5], dtype=np.int16),
        max_layer_count=5,
    )
    numpy_result = dynamic_solver.search_dynamic_catalog_exact(
        np.asarray([[10, 20, 30]], dtype=np.uint8),
        catalog,
        5,
        5,
        prefer_numba=False,
    )
    numba_result = replace(numpy_result, engine="numba")

    monkeypatch.setattr(dynamic_solver, "_NUMBA_AVAILABLE", True)
    monkeypatch.setattr(
        dynamic_solver,
        "search_dynamic_catalog_exact",
        lambda *args, prefer_numba=True: (
            numpy_result if not prefer_numba else numba_result
        ),
    )

    comparison = profile._compare_search_backends(
        np.asarray([[10, 20, 30]], dtype=np.uint8),
        catalog,
        5,
        5,
    )

    assert comparison["numpy"]["engine"] == "numpy"
    assert comparison["numba"]["engine"] == "numba"
    assert comparison["selected_candidate_identity"] is True
    assert comparison["distance_bitwise_identity"] is True
    assert comparison["numeric_identity_at_1e-12"] is True


def test_run_summary_keeps_measured_values_separate() -> None:
    runs = [
        {
            "elapsed_seconds": 2.0,
            "memory": {"observed_peak_delta_mb": 4.0},
            "cache": {"status": "miss_built"},
            "result": {"sha256": "same"},
        },
        {
            "elapsed_seconds": 1.0,
            "memory": {"observed_peak_delta_mb": 2.0},
            "cache": {"status": "miss_built"},
            "result": {"sha256": "same"},
        },
    ]

    summary = profile._summarize_runs(runs)

    assert summary["elapsed_seconds"]["median"] == 1.5
    assert summary["observed_peak_delta_mb"]["median"] == 3.0
    assert summary["result_sha256_all_identical"] is True
