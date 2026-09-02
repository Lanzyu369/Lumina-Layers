"""Contract for complete Lumina native-SVG benchmark evidence."""

from __future__ import annotations

import json
from pathlib import Path

import lumina_svg_core

from scripts import benchmark_native_svg_analysis as benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "progress" / "native-svg-fast-path-benchmark.json"
SOURCE_PROXY_PATH = REPO_ROOT / "test_images" / "benchmark.svg"
SUPPORTED_FIXTURE_PATH = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "supported_scale_fixture.svg"
)
def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_complete_vector_analysis_benchmark_contract() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == 2
    assert manifest["entrypoint"] == (
        "core.vector_engine.VectorProcessor.analyze_svg"
    )

    fixture = manifest["fixture"]
    fixture_bytes = SUPPORTED_FIXTURE_PATH.read_bytes()
    assert fixture["path"] == (
        "native/lumina-svg-core/benchmarks/supported_scale_fixture.svg"
    )
    assert fixture["classification"] == "derived_supported_scale"
    assert fixture["byte_size"] == len(fixture_bytes)
    assert fixture["provenance"]["selection"][
        "overlap_policy"
    ] == "disjoint_cell_bounds"
    assert len(fixture["canvas_user_units"]) == 2
    for key in (
        "path_count",
        "stroke_count",
        "stroke_only_count",
        "transform_count",
        "clip_count",
    ):
        assert fixture[key] >= 0

    parameters = manifest["parameters"]
    assert parameters == {
        "target_width_mm": 111.0,
        "tolerance_mm": 0.02,
        "build_type": "Release",
        "openmp_enabled": False,
        "caller_threads": 1,
    }

    host = manifest["host"]
    for key in (
        "platform",
        "platform_release",
        "machine",
        "processor",
        "python",
        "cpu_count",
        "memory_bytes",
    ):
        assert host[key]

    measurement = manifest["measurement"]
    assert measurement["warmup_runs"] == 1
    assert len(measurement["warm_runs_seconds"]) >= 3
    assert measurement["cache_policy"] == {
        "memory_cache_cleared_before_each_run": True,
        "artifact_cache_disabled": True,
    }
    for key in (
        "median_seconds",
        "p95_seconds",
        "range_seconds",
        "native_recorder_seconds",
        "native_kernel_seconds",
        "native_bounds_seconds",
        "native_replay_seconds",
        "native_topology_seconds",
        "native_normalize_raw_seconds",
        "native_composite_seconds",
        "native_normalize_visible_seconds",
        "native_export_seconds",
        "native_binding_conversion_seconds",
        "native_adapter_conversion_seconds",
        "native_geometry_total_seconds",
        "color_match_seconds",
        "orchestration_seconds",
    ):
        assert measurement[key] >= 0
    assert measurement["median_seconds"] > 0
    assert measurement["p95_seconds"] >= min(
        measurement["warm_runs_seconds"]
    )
    assert measurement["peak_rss_bytes"] > 0
    assert measurement["swap_delta_bytes"] >= 0
    assert measurement["median_threshold_seconds"] == 1.0
    assert measurement["p95_threshold_seconds"] == 1.25
    assert measurement["median_threshold_passed"] == (
        measurement["median_seconds"] <= 1.0
    )
    assert measurement["p95_threshold_passed"] == (
        measurement["p95_seconds"] <= 1.25
    )
    assert measurement["median_threshold_passed"] is True
    assert measurement["p95_threshold_passed"] is True

    output = manifest["output"]
    assert output["geometry_backend"] == "native"
    assert output["native_cache_hit"] is False
    assert output["raw_shape_count"] > 0
    assert output["visible_shape_count"] > 0
    assert output["matched_shape_count"] == output["visible_shape_count"]
    assert output["silhouette_component_count"] > 0
    assert output["coordinate_count"] > 0
    assert len(output["fingerprint"]) == 64
    assert output["stable_across_runs"] is True


def test_real_inputs_record_current_capability_without_identity_gates() -> None:
    manifest = _load_manifest()

    source_proxy = manifest["source_proxy"]
    assert source_proxy["classification"] in {"real_proxy", "real_proxy_fallback"}
    assert source_proxy["byte_size"] == SOURCE_PROXY_PATH.stat().st_size
    assert source_proxy["status"] in {"supported", "unsupported"}
    assert source_proxy["native_by_default_ready"] == (
        source_proxy["status"] == "supported"
    )
    if source_proxy["status"] == "supported":
        assert source_proxy["reason_code"] is None
    else:
        assert source_proxy["reason_code"]

    real = manifest["real_r4c1"]
    assert real["classification"] == "real_r4c1"
    assert real["status"] in {"supported", "unsupported", "unavailable"}
    assert real["native_by_default_ready"] == (
        real["status"] == "supported"
    )
    if real["status"] == "unavailable":
        assert real["reason_code"] is None
        assert real["source"] == "not_provided"

    large = manifest["large_regression"]
    assert large["minimum_byte_size"] == 50 * 1024 * 1024
    assert large["status"] in {"measured", "unavailable"}
    assert large["classification"] == "large_regression"
    assert large["classification"] != fixture_classification(manifest)
    assert large["searched_roots"]
    if large["status"] == "measured":
        assert large["byte_size"] >= large["minimum_byte_size"]
        assert large["peak_rss_bytes"] <= 2 * 1024**3
        assert large["swap_delta_bytes"] <= 256 * 1024**2
        assert large["rss_threshold_passed"] is True
        assert large["swap_delta_threshold_passed"] is True
    else:
        assert large["matching_files"] == []


def fixture_classification(manifest: dict) -> str:
    """Return the performance-fixture classification for comparison."""

    return manifest["fixture"]["classification"]


def test_benchmark_threshold_failures_are_process_fatal() -> None:
    manifest = {
        "measurement": {
            "median_threshold_passed": False,
            "p95_threshold_passed": True,
        },
        "large_regression": {
            "status": "measured",
            "rss_threshold_passed": True,
            "swap_delta_threshold_passed": False,
        },
    }

    assert benchmark._threshold_failures(manifest) == [
        "measurement.median_threshold_passed",
        "large_regression.swap_delta_threshold_passed",
    ]


def test_supported_scale_fixture_runs_directly_on_native_core() -> None:
    result = lumina_svg_core.analyze_svg(
        SUPPORTED_FIXTURE_PATH,
        target_width_mm=111.0,
        tolerance_mm=0.02,
        allow_strokes=False,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count > 0
    assert result.visible.geometry_count > 0
    assert result.silhouette.component_count > 0
